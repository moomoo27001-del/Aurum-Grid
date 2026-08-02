//+------------------------------------------------------------------+
//|                                              AURUM_GRID_EA.mq5    |
//| ML-regime-gated grid EA for XAU/USD.                             |
//| v2: adds weekend flatten, EnableTrading defaults to FALSE —      |
//| re-enable only after demo forward-testing, per the two live      |
//| losses this version was built to fix.                            |
//+------------------------------------------------------------------+
#property copyright "AURUM_GRID"
#property version   "2.00"
#property strict

input string  SignalServerURL      = "https://your-railway-app.up.railway.app/grid_signal";
input string  LogTradeURL          = "https://your-railway-app.up.railway.app/log_trade";
input int     PollIntervalSeconds  = 900;      // check for new grid signal every 15 min
input int     MagicNumber          = 990011;
input double  MaxSpreadPoints      = 400;      // safety: skip deployment if spread too wide
input bool    EnableTrading        = false;    // DEFAULT OFF — enable only after demo testing

input bool    EnableTelegram       = true;
input string  TelegramBotToken     = "";       // from @BotFather
input string  TelegramChatID       = "";       // your channel/chat ID

datetime lastPollTime = 0;
string   basketId = "";
datetime basketOpenTime = 0;
string   regimeAtOpen = "";
int      spacingAtOpen = 0;

//+------------------------------------------------------------------+
int OnInit()
  {
   EventSetTimer(PollIntervalSeconds);
   if(!EnableTrading)
      Print("AURUM_GRID_EA loaded with EnableTrading=false — dry run only, no orders will be placed.");
   return(INIT_SUCCEEDED);
  }

void OnDeinit(const int reason)
  {
   EventKillTimer();
  }

//+------------------------------------------------------------------+
void OnTimer()
  {
   CheckWeekendFlatten();
   ManageOpenBasket();     // check profit target / trail / equity stop first
   if(!HasOpenGridPositions())
      TryDeployGrid();
  }

void OnTick()
  {
   CheckEquityStopout();
  }

//+------------------------------------------------------------------+
//| Fetch signal from Railway server                                  |
//+------------------------------------------------------------------+
string FetchGridSignal()
  {
   string headers = "Content-Type: application/json\r\n";
   char   post[], result[];
   string resultHeaders;
   int    timeout = 5000;

   int res = WebRequest("GET", SignalServerURL, headers, timeout, post, result, resultHeaders);
   if(res == -1)
     {
      Print("WebRequest failed. Add the signal server URL to Tools->Options->Expert Advisors->WebRequest allowed URLs. Error: ", GetLastError());
      return("");
     }
   return(CharArrayToString(result));
  }

//+------------------------------------------------------------------+
//| Deploy grid based on server signal                                |
//+------------------------------------------------------------------+
void TryDeployGrid()
  {
   if(!EnableTrading) return;

   string json = FetchGridSignal();
   if(json == "") return;

   if(StringFind(json, "\"action\":\"stand_down\"") >= 0)
     {
      return;
     }

   if(StringFind(json, "\"action\":\"deploy_grid\"") < 0)
      return;

   double spread = (double)SymbolInfoInteger(_Symbol, SYMBOL_SPREAD);
   if(spread > MaxSpreadPoints)
     {
      Print("Spread too wide (", spread, "), skipping grid deployment.");
      return;
     }

   int spacingPoints   = ParseIntField(json, "spacing_points");
   int maxLevels        = ParseIntField(json, "max_levels");
   double baseLot        = ParseDoubleField(json, "base_lot");

   int buyLevels  = ParseIntField(json, "\"buy_levels\"");
   int sellLevels = ParseIntField(json, "\"sell_levels\"");
   if(buyLevels == 0 && sellLevels == 0) { buyLevels = maxLevels/2; sellLevels = maxLevels/2; }

   basketId = "AGRID_" + IntegerToString((int)TimeCurrent());
   basketOpenTime = TimeCurrent();
   regimeAtOpen = (StringFind(json, "\"ranging\"") >= 0) ? "ranging" : "unknown";
   spacingAtOpen = spacingPoints;

   double point = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);

   for(int lvl = 1; lvl <= buyLevels; lvl++)
     {
      double price = bid - lvl * spacingPoints * point;
      double lot = CalcScaledLot(baseLot, lvl);
      PlacePending(ORDER_TYPE_BUY_LIMIT, price, lot);
     }
   for(int lvl = 1; lvl <= sellLevels; lvl++)
     {
      double price = ask + lvl * spacingPoints * point;
      double lot = CalcScaledLot(baseLot, lvl);
      PlacePending(ORDER_TYPE_SELL_LIMIT, price, lot);
     }

   Print("AURUM_GRID deployed: buyLevels=", buyLevels, " sellLevels=", sellLevels,
         " spacing=", spacingPoints, " regime=", regimeAtOpen);

   SendTelegramMessage(StringFormat("AURUM_GRID deployed | regime=%s | buy=%d sell=%d | spacing=%d pts",
                        regimeAtOpen, buyLevels, sellLevels, spacingPoints));
  }

double CalcScaledLot(double baseLot, int level)
  {
   double scale = 1.0 + (level - 1) * 0.12;
   if(scale > 1.6) scale = 1.6;
   double lot = NormalizeDouble(baseLot * scale, 2);
   return(lot);
  }

void PlacePending(ENUM_ORDER_TYPE type, double price, double lot)
  {
   MqlTradeRequest request;
   MqlTradeResult  result;
   ZeroMemory(request);
   ZeroMemory(result);

   request.action    = TRADE_ACTION_PENDING;
   request.symbol     = _Symbol;
   request.volume     = lot;
   request.type       = type;
   request.price      = NormalizeDouble(price, _Digits);
   request.magic      = MagicNumber;
   request.comment    = basketId;
   request.type_time  = ORDER_TIME_GTC;
   request.type_filling = ORDER_FILLING_RETURN;

   if(!OrderSend(request, result))
      Print("PlacePending failed: ", result.retcode, " ", result.comment);
  }

//+------------------------------------------------------------------+
//| Basket management: profit target, trailing, equity stopout        |
//+------------------------------------------------------------------+
bool HasOpenGridPositions()
  {
   for(int i = 0; i < PositionsTotal(); i++)
     {
      ulong ticket = PositionGetTicket(i);
      if(PositionSelectByTicket(ticket) && PositionGetInteger(POSITION_MAGIC) == MagicNumber)
         return(true);
     }
   for(int i = 0; i < OrdersTotal(); i++)
     {
      ulong ticket = OrderGetTicket(i);
      if(OrderSelect(ticket) && OrderGetInteger(ORDER_MAGIC) == MagicNumber)
         return(true);
     }
   return(false);
  }

double BasketFloatingProfit()
  {
   double total = 0;
   for(int i = 0; i < PositionsTotal(); i++)
     {
      ulong ticket = PositionGetTicket(i);
      if(PositionSelectByTicket(ticket) && PositionGetInteger(POSITION_MAGIC) == MagicNumber)
         total += PositionGetDouble(POSITION_PROFIT);
     }
   return(total);
  }

void ManageOpenBasket()
  {
   if(!HasOpenGridPositions()) return;

   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   double floatingProfit = BasketFloatingProfit();
   double profitPct = (floatingProfit / equity) * 100.0;

   double profitTarget = 1.2;
   if(profitPct >= profitTarget)
     {
      CloseAllGridPositions("profit_target");
     }
  }

void CheckEquityStopout()
  {
   if(!HasOpenGridPositions()) return;

   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   double floatingProfit = BasketFloatingProfit();
   double lossPct = (-floatingProfit / equity) * 100.0;

   double equityStopoutPct = 6.0;
   if(lossPct >= equityStopoutPct)
     {
      Print("EQUITY STOPOUT triggered at ", lossPct, "% drawdown. Closing basket.");
      CloseAllGridPositions("equity_stopout");
     }
  }

//+------------------------------------------------------------------+
//| Force-close everything before weekend market close, regardless   |
//| of P/L — avoids swap fees and weekend gap risk on an open basket.|
//| NEW in v2, directly fixes the Friday-hold issue.                 |
//+------------------------------------------------------------------+
void CheckWeekendFlatten()
  {
   if(!HasOpenGridPositions()) return;

   MqlDateTime dt;
   TimeToStruct(TimeGMT(), dt);

   // MQL5 day_of_week: 0=Sunday ... 5=Friday. Adjust hour/min if your
   // broker's actual weekend close time differs.
   if(dt.day_of_week == 5 && dt.hour >= 20 && dt.min >= 45)
     {
      Print("Weekend approaching — force-closing basket to avoid swap/gap risk.");
      CloseAllGridPositions("weekend_flatten");
     }
  }

void CloseAllGridPositions(string reason)
  {
   int filled = 0;
   double netProfit = 0;

   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong ticket = PositionGetTicket(i);
      if(PositionSelectByTicket(ticket) && PositionGetInteger(POSITION_MAGIC) == MagicNumber)
        {
         netProfit += PositionGetDouble(POSITION_PROFIT);
         filled++;
         ClosePositionByTicket(ticket);
        }
     }
   for(int i = OrdersTotal() - 1; i >= 0; i--)
     {
      ulong ticket = OrderGetTicket(i);
      if(OrderSelect(ticket) && OrderGetInteger(ORDER_MAGIC) == MagicNumber)
        {
         MqlTradeRequest request; MqlTradeResult result;
         ZeroMemory(request); ZeroMemory(result);
         request.action = TRADE_ACTION_REMOVE;
         request.order = ticket;
         OrderSend(request, result);
        }
     }

   LogTradeOutcome(filled, netProfit, reason);

   string prefix = (reason == "equity_stopout") ? "\u26A0\uFE0F EQUITY STOPOUT" :
                    (reason == "weekend_flatten") ? "\uD83D\uDCC5 Weekend flatten" :
                    "AURUM_GRID basket closed";
   SendTelegramMessage(StringFormat("%s | levels=%d | net=%.2f | reason=%s",
                        prefix, filled, netProfit, reason));
  }

void ClosePositionByTicket(ulong ticket)
  {
   MqlTradeRequest request; MqlTradeResult result;
   ZeroMemory(request); ZeroMemory(result);

   if(!PositionSelectByTicket(ticket)) return;

   request.action   = TRADE_ACTION_DEAL;
   request.symbol    = _Symbol;
   request.volume    = PositionGetDouble(POSITION_VOLUME);
   request.type      = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) ? ORDER_TYPE_SELL : ORDER_TYPE_BUY;
   request.position  = ticket;
   request.price     = (request.type == ORDER_TYPE_SELL) ? SymbolInfoDouble(_Symbol, SYMBOL_BID) : SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   request.magic     = MagicNumber;
   request.type_filling = ORDER_FILLING_RETURN;

   OrderSend(request, result);
  }

//+------------------------------------------------------------------+
//| Telegram notifications                                            |
//+------------------------------------------------------------------+
void SendTelegramMessage(string text)
  {
   if(!EnableTelegram || TelegramBotToken == "" || TelegramChatID == "") return;

   string url = "https://api.telegram.org/bot" + TelegramBotToken + "/sendMessage";
   string json = StringFormat("{\"chat_id\":\"%s\",\"text\":\"%s\"}", TelegramChatID, text);

   char post[], result[];
   string headers = "Content-Type: application/json\r\n";
   StringToCharArray(json, post, 0, StringLen(json));
   string resultHeaders;

   int res = WebRequest("POST", url, headers, 5000, post, result, resultHeaders);
   if(res == -1)
      Print("Telegram notify failed: ", GetLastError());
  }

//+------------------------------------------------------------------+
//| Feedback loop                                                     |
//+------------------------------------------------------------------+
void LogTradeOutcome(int levelsFilled, double netProfit, string closeReason)
  {
   string json = StringFormat(
      "{\"basket_id\":\"%s\",\"open_time\":\"%s\",\"close_time\":\"%s\","
      "\"levels_filled\":%d,\"net_profit\":%.2f,\"regime_at_open\":\"%s\","
      "\"spacing_points\":%d,\"close_reason\":\"%s\"}",
      basketId, TimeToString(basketOpenTime), TimeToString(TimeCurrent()),
      levelsFilled, netProfit, regimeAtOpen, spacingAtOpen, closeReason);

   char post[], result[];
   string headers = "Content-Type: application/json\r\n";
   StringToCharArray(json, post, 0, StringLen(json));
   string resultHeaders;

   int res = WebRequest("POST", LogTradeURL, headers, 5000, post, result, resultHeaders);
   if(res == -1)
      Print("LogTradeOutcome WebRequest failed: ", GetLastError());
  }

//+------------------------------------------------------------------+
//| Minimal JSON field parsers                                        |
//+------------------------------------------------------------------+
int ParseIntField(string json, string field)
  {
   int pos = StringFind(json, field);
   if(pos < 0) return(0);
   int colonPos = StringFind(json, ":", pos);
   int commaPos = StringFind(json, ",", colonPos);
   int bracePos = StringFind(json, "}", colonPos);
   int endPos = (commaPos > 0 && (commaPos < bracePos || bracePos < 0)) ? commaPos : bracePos;
   string val = StringSubstr(json, colonPos + 1, endPos - colonPos - 1);
   StringReplace(val, "\"", "");
   return((int)StringToInteger(val));
  }

double ParseDoubleField(string json, string field)
  {
   int pos = StringFind(json, field);
   if(pos < 0) return(0.0);
   int colonPos = StringFind(json, ":", pos);
   int commaPos = StringFind(json, ",", colonPos);
   int bracePos = StringFind(json, "}", colonPos);
   int endPos = (commaPos > 0 && (commaPos < bracePos || bracePos < 0)) ? commaPos : bracePos;
   string val = StringSubstr(json, colonPos + 1, endPos - colonPos - 1);
   StringReplace(val, "\"", "");
   return(StringToDouble(val));
  }
//+------------------------------------------------------------------+
