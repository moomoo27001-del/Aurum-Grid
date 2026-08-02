# AURUM_GRID v2 — post-mortem fixes

Two live baskets both lost money because the regime/direction logic was blind
to fast intraday moves (H4 EMA trend filter is too slow to see a move that
completes within a few hours). This version adds a faster, independent check
and tightens risk parameters. **Trading defaults to OFF in the EA** — this
needs demo forward-testing before it touches live funds again.

## What changed

1. **New M15 fast-momentum check** (`indicators.py`, `data_feed.py`) — looks
   at price change over the last ~3 hours on M15, which catches sharp moves
   the H4 EMA filter can't see yet.
2. **Hard stand-down on strong fast momentum** (`grid_logic.py`) — if that
   M15 check shows a move ≥0.7% in either direction, the grid won't deploy
   at all, regardless of what the regime classifier says. This is the fix
   most directly targeting both live losses.
3. **Direction bias now uses the fast signal**, not just H4 — when the fast
   M15 trend shows real movement, it overrides the slower H4 read.
4. **Wider spacing (250pt vs 150pt), fewer levels (4 vs 6)** — less exposure
   burned through per basket if a move does get through.
5. **Higher regime confidence threshold (0.65 vs 0.55)**.
6. **Weekend flatten** (EA) — force-closes any open basket Friday 20:45 UTC
   onward regardless of P/L, so nothing gets held over the weekend and hit
   with swap fees again.
7. **Friday deployment cutoff** (server) — no *new* grids open after Friday
   12:00 UTC, so baskets have time to resolve before the weekend flatten.
8. **News blackout** — blocks deployment ±30 min around high-impact USD
   releases, via the Forex Factory calendar feed.
9. **`EnableTrading` now defaults to `false`** in the EA — you must
   explicitly turn it on, so a fresh install can't accidentally go live.

## What did NOT change

- The XGBoost regime model itself (`model.json`) — the new fast-momentum
  check is a separate layer, not fed into the trained model, so no
  retraining was needed to ship this fix.
- Equity stopout (still 6%), basket profit target (still 1.2%).

## Before going live again

1. **Demo test for at least a few weeks.** Specifically watch for how often
   `fast_momentum_hard_stop` triggers in the `/grid_signal` response — if
   it's firing on nearly every check, the 0.7% threshold may need tuning
   (too tight = never deploys; too loose = doesn't catch real moves).
2. Confirm the weekend flatten actually fires — the easiest way is to leave
   a basket open into a Friday evening on demo and watch for the Telegram
   "Weekend flatten" message and the position closing.
3. Only then set `EnableTrading = true` on the EA, and start with minimum
   lot size again even then.

## Setup (unchanged from before)
See the original setup steps: Twelve Data key, Railway env vars,
WebRequest allowlist, EA installation. The only new required step is none —
all new logic is server-side and auto-deploys with the code push.
