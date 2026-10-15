# User stories: Paper Scanner

Stories are written from the role that feels the outcome. They match the running desk: paper by default, Eye sizes and keeps a preset until a real sample pays, assistants only brief, and Phantom never gives the server a key. Each story can be copied into a backlog as an independent item.

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

Acceptance: Approve appears only for a pending order while wallet trading is on and the lab gate is open. The button covers a buy and, separately, a sell at a ladder, stop, liquidity drop, or vanish. An empty signature is rejected. A signature is marked sent only after it is confirmed and the linked wallet gained the mint on a buy or spent it on a sell. The paper position does not wait for that signature.

Priority: next.

### OP-11 See the assistants working

As an operator, I want Eye at the head of a floor and the four assistants at stations, so that I can see who is briefing without reading a list.

Acceptance: the floor sits under the eight role cards. A station shows Briefing and a line to Eye only when that assistant has a note. The last paper pick and the latest Eye decision are the live book, not a sample balance. The Agent tab shows the same staff under the goal “A paper book that pays,” with the full note on each card.

Priority: now.

### OP-12 See what a trade costs

As an operator, I want the round-trip cost of each open position in dollars, so that I can see how much of a small win the fees and slippage take.

Acceptance: the Book tab has a Cost column. A $5.50 ticket in a $10,000 pool shows $0.85. The Closed PnL tile and the equity panel also show SOL, because USD moves with the SOL price.

Priority: now.

### OP-13 Notice when the desk stops

As an operator, I want a warning when the scan stalls or a feed is down, so that a quiet book is not mistaken for a calm market.

Acceptance: a warning shows above the tabs when the last scan is more than 5 minutes old, or any feed is `down`. It names the minutes and the feeds, and it clears on the next good scan. A paper-mode halt does not trigger it.

Priority: now. An alert outside the page is OP-14.

### OP-14 Get told when something needs me

As an operator, I want a push, Telegram, or email message when a sell order queues, the scan stalls, live trading halts, or the lab gate changes, so that a stop does not wait for me to open the page.

Acceptance: a queued sell sends one message. A sell pending more than 5 minutes is marked stale and re-quoted. The message contains no token, PIN, or key.

Priority: next. Required before live money (G2, G13).

### OP-15 Trust the spend lock and the login

As an operator, I want a slow lock hash, a longer code, and a limit on login guesses, so that a leaked file or an open URL cannot be brute-forced.

Acceptance: the lock uses scrypt or Argon2. Live trading needs a code of 8 or more characters. An existing code still works once and is then re-hashed. Failed dashboard logins are rate-limited per IP. The site is HTTPS only.

Priority: next. Required before live money (G3, G5).

### OP-16 See who armed the wallet

As an operator, I want a record of every Connect, Allow, Halt, Resume, and lock change, so that I can tell afterwards who did what.

Acceptance: each action writes time, action, actor, reason, and outcome. The record has no secrets.

Priority: next. Required before live money (G4).

## Eye

### EY-1 Size the next paper buy

As Eye, I want to choose the USD size from equity, the fee reserve, and recent win rate, so that a cold or losing book does not bet the whole wallet.

Acceptance: free cash under $4 sizes the trade at $0 and the engine skips it. Before 30 closes the size is $5.50, or $5 when free cash is at least $5 and under $5.50, otherwise $0. After 30 closes, a recent win rate under 25% sizes $4, under 45% sizes 10% of equity clamped to $4–$8, and a stronger book sizes 15% clamped to $6–$12. Size never exceeds free cash, and a result under $4 is $0. The buy note includes the SOL size, the USD size, and the words phantom paper.

Priority: now.

### EY-2 Leave fee SOL in the wallet

As Eye, I want $3 to $5 left unused, so that a paper fill behaves like a Phantom wallet that must pay fees.

Acceptance: the reserve used for free-cash math is clamped into that band. The default book keeps $5.

Priority: now.

### EY-3 Refill a flat book without rotating presets

As Eye, I want a flat book refilled to $50 on the same preset, so that one bust does not throw away the rules before the sample is real.

Acceptance: refill runs only when nothing is open, the run has at least one close, and the sizing rule returns $0 for the next buy. A wallet with $4 to $5 free and fewer than 30 closes refills; it does not sit skipping every entry. The ledger gets a `RESET`. The grind index does not change. A lock happens only at 50 or more sized closes, a mean return above 0, and a 95% interval lower bound above 0. Later refills keep that lock. A lab shadow book can name a winner. Eye does not copy it onto the desk by itself.

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

Acceptance: a second hire of the same name is refused. A name about spending, sizing, or the wallet is refused. Powers outside read scan, read trades, write note, and halt live are dropped. The floor shows the four stations. The Agent tab shows their notes.

Priority: now.

## Vet

### VT-1 Brief Eye on rugs

As Vet, I want to tell Eye whether RugCheck is reporting and whether I can see holder clusters, so that Eye does not treat a missing map as a clean bill of health.

Acceptance: the brief says RugCheck is live or not reporting yet. Without `BUBBLEMAPS_API_KEY`, Vet names up to three coins and says the public map was opened with the mint as the address and `solana` as the chain, and that cluster scores still need a key. With a key and a successful read, the brief says clusters can be read. Vet does not place an order.

Priority: now.

### VT-2 Block a dangerous holder picture

As Vet, I want a rugged flag, a danger report, a score of 50 or more, a wallet holding 35% or more, or a tight Bubblemaps cluster to skip the name, so that those facts reach the scorer rather than only the briefing.

Acceptance: the candidate note contains the `rugcheck:` or `bubblemap:` reason. A missing Bubblemaps key does not, by itself, skip every name. The public map link is `https://v2.bubblemaps.io/map?address=<mint>&chain=solana`.

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

Acceptance: a signal waits about 45 seconds and is abandoned after about 70 seconds without a price. The fill price includes slippage of 3% plus twice the trade size over pool liquidity, capped at 80%. The open books a 1% fee plus $0.20. Positions are priced every 12 seconds. A pool at half the entry liquidity sells the rest. Three confirmed absences close near 10% of the last price. A stop fills at the next poll, not at the stop level. Partial sells reduce `left` and write `SELL`. The final sell writes `SELL` and `CLOSED` and removes the position.

Priority: now.

### EN-4 Rank wallets without copying them into a live order

As the paper engine, I want a wallet table of PnL, win rate, trades, and median hold, so that the Book tab can show who was discovered.

Acceptance: addresses link to Solscan. Discovery uses the Helius key on the server. A ranked wallet does not by itself arm Phantom.

Priority: now.

### EN-5 Write the day

As the paper engine, I want a report when 24 hours have passed, so that the Reports tab has one row per window.

Acceptance: the row counts closes, wins, buys, skips, fades, best, worst, and tune edits inside the window. The origin is the first ledger time, not the server boot, once the ledger exists.

Priority: now.

### EN-6 Never lose the book to a bad write

As the paper engine, I want every save to be all-or-nothing and a daily copy of the book, so that one crash or a lost volume does not end the run history.

Acceptance: JSON files are written to a temp file and renamed. The first scan of each UTC day copies the book files into `backups/<date>/` and writes `.ok`. `config.json` and `.env` are never copied. A restore from that folder has been tested once.

Priority: now for the copy. Next for the tested restore.

### EN-7 Write one clock

As the paper engine, I want new rows in UTC, so that the desk, the reports, and the lab agree when the two services run in different timezones.

Acceptance: new rows are `YYYY-MM-DDTHH:MM:SSZ`. Older local rows still parse for win rate, cooldown, and report windows. The screen shows both as `MM-DD HH:MM`.

Priority: now.

### EN-8 Check the paper fill against a real quote

As the paper engine, I want a Jupiter quote logged beside each paper fill, so that the live gate does not rest on a cost model nobody measured.

Acceptance: each paper fill stores the quote, price impact, and route, or `no_route`. Quote rows cover at least 95% of fills. The lab reports the median and p90 gap between quote and paper fill per side, and the no-route share. A buy whose quoted impact is over 5% is refused. Live opens only when that gap is under 3 percentage points. Live slippage is set from the quoted impact, not a fixed 300 bps.

Priority: paper logging built (`quotes.py`, `/api/quotes`). The impact refusal and live slippage are next. Required before live money (G1, G6).

### EN-10 Trade enough to be measured

As the paper engine, I want the paper entry on the two-source rule (2 sources, score 65 or more, 5-minute move up to 60%), so that the desk-ladder book records trades every day instead of none.

Acceptance: `tune.ensure_entry_rule()` applies it once and writes a change note. A locked strategy is left alone. The lab keeps the 3-source rule as the `strict` books.

Priority: now.

### EN-9 Ship every module

As the paper engine, I want the deploy image to contain every module the server imports, so that a push to `main` does not take the desk down.

Acceptance: a new Python file is added to the `COPY` line of the root `Dockerfile` in the same commit. A clean image starts without `ModuleNotFoundError`.

Priority: now.

## Later, not a current role

### LA-1 Social feeds

As an operator, I want X and Telegram called out as off, so that I do not think a social signal is in the score.

Acceptance: both chips stay `off`. Adding a key does not change `enter` until a story explicitly connects them.

Priority: later.

### LA-2 Bubblemaps key

As Vet, I want a Bubblemaps key when the operator has one, so that cluster, top-10, and score blocks can fire.

Acceptance: without the key the chip is `key` and the public map still opens. With the key, a cluster of 20% or more, a top 10 of 55% or more, or a score under 40 becomes a skip.

Priority: next, only after the operator supplies the key. Do not invent one.

## Lab

The lab has no login on the desk. It is a second service that reads the desk and never trades.

### LB-1 Record what the desk saw

As the lab, I want each scan and each desk trade stored in my own database, so that a shadow book can be scored without touching the paper wallet.

Acceptance: the lab calls the desk with the dashboard token and writes hits, episodes, prices, and desk trades. It does not write `trades.csv`, `bank.json`, or any desk key. A missing or placeholder token does not count as a recorded scan.

Priority: now.

### LB-2 Keep live trading closed until the ladder book is real

As the lab, I want one readiness flag for the `desk-ladder-real` book (the desk ladder with one entry per scan and at most five open), so that the desk does not arm Phantom on a short or lucky sample.

Acceptance: ready requires at least 100 closes, a span of at least 14 days, an interval low above 0, and a random percentile of at least 90. Anything else, including a failed fetch, leaves the desk’s live queue closed. Desk equity is not an input.

Priority: next.

### LB-3 Test a runner without switching the desk

As the lab, I want a `desk-runner` book that sells half at 2x and trails the rest, so that the desk can see whether that beats the 5x ladder before anyone changes the live rules.

Acceptance: the runner is a shadow book only. The desk stays on the 5x ladder until that row beats it with an interval that excludes zero, and even then the switch is a manual copy onto the tune fields.

Priority: next.

### LB-4 Find the ticket size that survives costs

As the lab, I want the desk ladder scored at $5.50, $8, and $12, so that the size that goes live is the one whose book held up after the flat fee.

Acceptance: the report has a ticket-size block with n, total, mean, win rate, and verdict for each size. The desk does not change its size from this block by itself.

Priority: now.

### LB-5 Beat doing nothing

As the lab, I want a hold-SOL baseline and a buy-every-tracked-name baseline, so that a shadow book is judged against something simple.

Acceptance: both baselines print under the books. Neither counts as a book for the live gate.

Priority: now. Tagging episodes with SOL trend and launch volume is next.

### LB-6 Not crown a lucky book

As the lab, I want each of twenty research books compared with the filters-only ladder on the same signals, picks frozen after an explore week, and only those picks judged on a confirm week, so that picking the best of twenty books does not overstate the edge.

Acceptance: the report shows a paired bootstrap interval against `filters-ladder`. The top 3 by paired difference with 30 or more trades are frozen once, with the count of books tried. The confirm week scores only the frozen picks.

Priority: now (G8).

### LB-11 Say whether there is an edge

As the operator, I want one weekly verdict, so that I know whether to keep going, change costs, or stop.

Acceptance: Edge found needs a frozen pick with 50 or more confirm-week trades, an interval low above $0 per trade after quote-calibrated costs, and a mean above buy-every-name and hold-SOL. Positive but short, or an interval spanning zero, is Not yet (one more confirm week). Gross positive but net negative is Costs only. Otherwise No edge: stop the live plan, keep the lab as research, add no agents.

Priority: now.

### LB-8 Say where the money goes

As the lab, I want each trade split into price move, stop gap, slippage, fee, and the $0.20, and a diagnosis of weak signal, costs, or exits, so that the next fix targets the real leak.

Acceptance: the parts sum to each trade's PnL. The diagnosis lists its evidence, or says too little data.

Priority: now.

### LB-9 Learn the score from outcomes

As the lab, I want the desk's signal features logged on every candidate and a simple model trained on them, so that hand-set points can be replaced only when data says so.

Acceptance: the label is peaked 1.5X before a 35% drop, before costs. It waits for 100 positive examples and 500 labeled coins with features. Tests on an untouched final week. Says adopt only when the model's AUC is above 0.5 at its low bound and above the hand score. Adoption is by hand. After 500 coins with no model beating random and every book negative, the report says to stop adding agents.

Priority: now for logging. The verdict needs about 500 coins collected after this change.

### LB-10 Trade less in bad markets

As the desk, I want to skip entries when the lab says the market is cold or the score bucket does not pay after costs, so that no trade is a valid action.

Acceptance: only applies when `LAB_URL` and `LAB_KEY` are set. A pause needs 3 days of data and cold markets that lost more than warm ones. A bucket needs 100 coins. The skip note starts `lab:`.

Priority: now. On since Oct 14, 2026, when `LAB_URL` and `LAB_KEY` were set on the desk.

### LB-7 Say what predicts a loss

As the lab, I want outcomes by decision, score, source count, and skip reason, and each losing desk close tagged, so that the operator can see whether the score means anything.

Acceptance: four outcome tables and the tags rug, gave back gains, slow bleed, and sold too early are in every report.

Priority: now.
