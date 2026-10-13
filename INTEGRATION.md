# Changes to make INSIDE the Paper Scanner desk

The Lab measures; these edits apply what the measurements (and basic risk logic) call for.
I could not see the desk's source, so each item says what to change, not where.

## 1. Stop locking a strategy on tiny samples
- Lock only at >= 50 closes (not 15), AND mean return per trade > 0 with the 95% bootstrap
  interval's lower bound above 0 after realistic costs. Copy `summarize()` from lab/sim.py.
- Size by win rate only after >= 30 closes. Before that use a fixed size ($5-$6).
- Do not "advance the grind preset" after every bust. A bust on 5-15 trades is mostly luck.
  Let the Lab's shadow books compare the presets, then adopt the winner deliberately.

## 2. Make paper fills as harsh as the Lab's
- Entry: use the price 30-60s after the signal, not the signal-time price.
- Slippage per side = 3% + 2 x trade_usd / pool_liquidity_usd. Fee 1% per side. $0.20 fixed per transaction.
- On a stop, assume the exit fills at the NEXT poll price, never the stop level.
- A token that vanishes from DexScreener for 3 polls: close at ~10% of the last price.

## 3. Exit on rug signals, not only price
- Sell the rest if pool liquidity falls 50% from entry. (The Lab test shows this helps on
  slow liquidity pulls; one-step rugs cannot be beaten at a 60s poll.)
- Poll open positions every 10-15s instead of 45-60s.
- Optional: Helius websocket on the creator and top-3 holders; sell on their first sell.

## 4. Test a runner exit before keeping the 5x cap
Sell 50% at 2x, then trail the rest 30% from the peak with no cap. Do not switch until the Lab's
"grind-1 + runner" row beats the ladder row with a CI that excludes zero.

## 5. Log what the Lab needs
Make `/api/candidates` include, for every candidate: mint, symbol, score, decision, note, sources,
change_5m, mcap, liq, price_sol. Keep skipped coins in the response too, with the skip reason in `note`.

## 6. Live-trading gaps (fix before any live use)
- `/api/phantom/done` must reject an empty signature, then confirm it on-chain
  (`getSignatureStatuses`) before marking an order `sent`.
- There is a live BUY queue but no live SELL path. A live position needs an exit plan the operator
  can actually execute (approve-to-sell notifications at the ladder/stop levels), or live stays off.
- Judge live-readiness by the Lab, not by the desk's own PnL: >= 100 closes over >= 2 weeks, CI above
  zero after realistic costs, and a strategy percentile above ~90% vs random.

## 7. Earlier entries (optional, bigger change)
Replace 45s polling with a stream (PumpPortal data websocket or Helius) and add features that are
available in the first minutes: unique buyers per minute, buy/sell ratio, creator holding, bonding-curve progress.
Add the feature to the candidate payload and let the Lab test it.
