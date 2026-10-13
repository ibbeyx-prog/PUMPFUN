# User stories: Paper Scanner

Stories are written from the role that feels the outcome. They match the running desk: paper by default, Eye sizes and grinds, assistants only brief, and Phantom never gives the server a key. Each story can be copied into a backlog as an independent item.

Priority words: now (the desk already depends on it), next (needed before live use is trusted), later (not connected).

## Operator

### OP-1 See the desk without a manual refresh

As an operator, I want the equity, feeds, and phase to update on their own, so that I can leave the page open.

Acceptance: after login the page polls every 5 seconds. A 401 clears the saved token and returns to login. A network error shows "Can't reach server" and does not wipe the last good numbers.

Priority: now.

### OP-2 Know this is paper

As an operator, I want a paper badge and a banner that names the fee reserve, so that I do not mistake a simulated fill for a Phantom send.

Acceptance: the banner shows Eye's current trade size and the reserve while wallet trading is off. It changes to the lock-and-approve warning only when wallet trading is on.

Priority: now.

### OP-3 Read who would be bought

As an operator, I want each scanned name to show its score, call, sources, size, liquidity, 5-minute move, RugCheck, and holder map, so that I can see why it is an entry or a skip.

Acceptance: the Scan tab lists up to 12 names. `enter`, `watch`, and `skip` are visually distinct. The mint opens on DexScreener, RugCheck, and Bubblemaps. An empty scan says the first pass is still running.

Priority: now.

### OP-4 Read the book in dollars

As an operator, I want equity, realized PnL, and free cash in USD, with the SOL price beside them, so that a $50 paper wallet is understandable.

Acceptance: equity uses the bank's SOL plus unrealized PnL, times the SOL price. Start stays $50 across a SOL move. Free to invest is equity minus the reserve and minus capital still in open trades.

Priority: now.

### OP-5 Inspect an open paper position

As an operator, I want the multiple, fraction left, age, and Eye's tip on each open mint, so that I can see whether a ladder, stop, or early cut is in play.

Acceptance: the Book tab lists open positions and, separately, the latest ledger rows with event, note, and PnL. No open positions has its own empty line.

Priority: now.

### OP-6 Read a day

As an operator, I want one report per 24-hour window, so that I can see closes, win rate, and rule edits without exporting the ledger.

Acceptance: the Reports tab is empty until the first window completes, and it names when the next report will be written. Each row includes the narrative sentence.

Priority: now.

### OP-7 Ask the book a question

As an operator, I want a chat dock that answers from this book's positions, PnL, and last report, so that I do not have to hunt through tables.

Acceptance: the dock sends the dashboard token. History survives a reload, keeps the latest 80 messages, and does not place a trade.

Priority: now.

### OP-8 Connect Phantom without handing over the key

As an operator, I want to connect the wallet that is already in the browser, so that the desk learns my public address and nothing else.

Acceptance: the server stores only the address. A missing Phantom extension is explained in the control. Disconnecting, or turning trades off, returns the halt to paper mode.

Priority: now.

### OP-9 Set a spend lock

As an operator, I want a lock code before any live buy can be queued, so that an open tab cannot spend by itself.

Acceptance: the code is 4 to 64 characters. The API never returns the code, salt, or hash. Five wrong attempts halt with `spend lock`. Eye cannot clear that halt.

Priority: now.

### OP-10 Approve one live buy

As an operator, I want a single Approve click that asks Phantom to sign, so that a paper entry cannot become a chain transaction without me.

Acceptance: Approve appears only for a pending order while wallet trading is on. Cancel or a rejected signature does not mark the order sent. The paper position is independent and may already be open.

Priority: next.

## Eye

### EY-1 Size the next paper buy

As Eye, I want to choose the USD size from equity, the fee reserve, and recent win rate, so that a cold or losing book does not bet the whole wallet.

Acceptance: free cash under $4 sizes the trade at $0 and the engine skips it. Under five closes, size is 10% of equity clamped to $4–$8. Worse than a 25% recent win rate sizes $4. A stronger book can size up to $12 and never above free cash. The buy note includes the SOL size, the USD size, and the words phantom paper.

Priority: now.

### EY-2 Leave fee SOL in the wallet

As Eye, I want $3 to $5 left unused, so that a paper fill behaves like a Phantom wallet that must pay fees.

Acceptance: the reserve used for free-cash math is clamped into that band. The default book keeps $5.

Priority: now.

### EY-3 Grind until a run pays

As Eye, I want a flat book refilled to $50 and the next of four presets installed, so that I can keep testing rules without the operator resetting by hand.

Acceptance: refill runs only when nothing is open, the run has at least one close, and free cash is under $4. The ledger gets a `RESET`. A run with at least 15 closes, at least a 30% win rate, and positive SOL PnL locks the rules instead of changing them. Later refills keep the lock.

Priority: now.

### EY-4 Learn from the public market

As Eye, I want to search and then fetch one page, so that market notes are tied to a real source.

Acceptance: research stores 4 to 6 notes, each under 240 characters, at most once a day after success. A failure retries in an hour and does not pretend notes were saved. Notes are labeled unverified. A note that tells Eye to change the budget or the trade size has no effect.

Priority: now.

### EY-5 Use what the tools found

As Eye, I want a note that smart-wallet copies arrive late to remove their score bonus, so that the scan stops paying extra for a fill I cannot get.

Acceptance: a matching web note makes candidates say `eye: copy arrives late` and adds 0 points instead of 12. DexScreener's own scan sentence does not trigger the rule.

Priority: now.

### EY-6 Refuse to loosen a hostile book

As Eye, I want review blocked from lowering the entry score, widening the 5-minute cap, or dropping the source minimum while research says the regime is hostile, so that a model reply cannot undo a cautious book.

Acceptance: other in-bound changes still apply. Locked budget fields never apply. A locked strategy skips review entirely.

Priority: now.

### EY-7 Halt live trading, never resume it

As Eye, I want to stop wallet trading when the book says so, so that a losing run cannot keep a live wallet armed.

Acceptance: `halt_live: true` from review, or Risk when wallet trading is actually on, sets the halt. No API and no model JSON turns `wallet_trade` back on. Only the operator can allow trades again, and only with the lock code.

Priority: now.

### EY-8 Hire a paper desk and no one else

As Eye, I want Vet, Scan watch, Scribe, and Risk on staff, so that I am briefed before I change a rule.

Acceptance: a second hire of the same name is refused. A name about spending, sizing, or the wallet is refused. Powers outside read scan, read trades, write note, and halt live are dropped. The desk line lists who is assisting.

Priority: now.

## Vet

### VT-1 Brief Eye on rugs

As Vet, I want to tell Eye whether RugCheck is reporting and whether I can see holder clusters, so that Eye does not treat a missing map as a clean bill of health.

Acceptance: the brief says RugCheck is live or not reporting yet. Without `BUBBLEMAPS_API_KEY` the brief says clusters cannot be checked. With a key and a successful read, the brief says clusters can be read. Vet does not place an order.

Priority: now.

### VT-2 Block a dangerous holder picture

As Vet, I want a rugged flag, a danger report, a score of 50 or more, a wallet holding 35% or more, or a tight Bubblemaps cluster to skip the name, so that those facts reach the scorer rather than only the briefing.

Acceptance: the candidate note contains the `rugcheck:` or `bubblemap:` reason. A missing Bubblemaps key does not, by itself, skip every name. The public map link still opens.

Priority: now.

## Scan watch

### SW-1 Put names in front of Eye

As Scan watch, I want to read the current candidates and name up to three that would enter, so that Eye sees the same list the operator sees.

Acceptance: if the scan has no rows, the brief says there is nothing to put in front of Eye. If none would enter, the brief counts the names and says none is clean. If some would enter, it lists symbol and score for the top three.

Priority: now.

### SW-2 Not outrun the scan

As Scan watch, I want a second brief after the first scan posts names, so that I do not stay stuck on "nothing to put in front of you" once the market text has names.

Acceptance: the eye loop retries once, about 50 seconds later, when the first market sentence says names are not posted yet. Later passes wait the normal 10 minutes.

Priority: now.

## Scribe

### SC-1 Tell Eye if the run is paying

As Scribe, I want to count closes and SOL PnL since the last reset, so that Eye does not lock a strategy on an old, wiped book.

Acceptance: fewer than five closes produces a brief that there is not enough evidence. Five or more reports wins, count, SOL PnL, and whether that is short of a 30% win rate. Rows before `RESET` are excluded.

Priority: now.

### SC-2 Leave the rules alone when the sample is short

As Scribe, I want the brief to recommend keeping the rules when the win rate is under 30%, so that Eye does not treat a handful of closes as a strategy.

Acceptance: the brief states the shortfall. It does not change `trade_usd`, the reserve, or the budget.

Priority: now.

## Risk

### RK-1 Leave paper mode alone

As Risk, I want to see that wallet trading is already off and say so, so that a paper halt is not rewritten on every pass.

Acceptance: when `wallet_trade` is false, Risk does not call halt again. The brief includes the close count and SOL PnL and says the wallet is not being armed.

Priority: now.

### RK-2 Stop a live wallet while the book is losing

As Risk, I want to halt wallet trading when it is actually on, so that live buys stop even if a paper scan continues.

Acceptance: halt reason is Eye's halt. The operator must enter the lock code to allow trades again. Risk cannot set the trade size.

Priority: now.

## Paper engine

These are system stories. They have no login. They are here so a backlog can track the loop the roles depend on.

### EN-1 Merge the feeds

As the paper engine, I want one row per mint across pump.fun, DexScreener, GMGN, Birdeye, and FOMO, so that agreement is visible as a source list.

Acceptance: FOMO counts only Solana network `1399811149`. A FOMO-only or pump.fun-only name cannot be `enter`. Birdeye or DexScreener or GMGN can confirm. FOMO is read at most hourly.

Priority: now.

### EN-2 Skip for the written reasons

As the paper engine, I want hard skips for cap, liquidity, age, chase, rug, bundler, wash, and source count, so that the note on the Scan row matches the rule that fired.

Acceptance: each skip reason is in the candidate note. At most one new position is opened per scan. A mint bought in the last 180 minutes is not bought again. A missing DexScreener SOL price is logged as `SKIP` and does not open a position.

Priority: now.

### EN-3 Exit on a schedule

As the paper engine, I want the ladder, the two-poll stop, the 90-minute time stop, and the early cut, so that a paper position does not sit forever.

Acceptance: partial sells reduce `left` and write `SELL`. The final sell writes `SELL` and `CLOSED` and removes the position. The fee of 0.002 SOL is on the open.

Priority: now.

### EN-4 Rank wallets without copying them into a live order

As the paper engine, I want a wallet table of PnL, win rate, trades, and median hold, so that the Book tab can show who was discovered.

Acceptance: addresses link to Solscan. Discovery uses the Helius key on the server. A ranked wallet does not by itself arm Phantom.

Priority: now.

### EN-5 Write the day

As the paper engine, I want a report when 24 hours have passed, so that the Reports tab has one row per window.

Acceptance: the row counts closes, wins, buys, skips, fades, best, worst, and tune edits inside the window. The origin is the first ledger time, not the server boot, once the ledger exists.

Priority: now.

## Later, not a current role

### LA-1 Social feeds

As an operator, I want X and Telegram called out as off, so that I do not think a social signal is in the score.

Acceptance: both chips stay `off`. Adding a key does not change `enter` until a story explicitly connects them.

Priority: later.

### LA-2 Bubblemaps key

As Vet, I want a Bubblemaps key when the operator has one, so that cluster, top-10, and score blocks can fire.

Acceptance: without the key the chip is `key` and the brief says clusters are unchecked. With the key, a cluster of 20% or more, a top 10 of 55% or more, or a score under 40 becomes a skip.

Priority: next, only after the operator supplies the key. Do not invent one.
