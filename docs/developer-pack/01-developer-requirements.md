# Developer requirements: Paper Scanner

Paper Scanner is a single-operator Solana meme-coin desk. It scans public feeds, simulates a Phantom-style wallet, and lets an agent named Eye size paper buys and tighten paper rules. Live spending is off unless the operator connects Phantom, sets a spend lock, and approves each signature in the browser.

## 1. Product rules

- The default mode is paper. Startup halts live trading with the reason `paper mode`.
- A paper buy spends simulated SOL from a bank that starts at $50. It does not broadcast a transaction.
- Eye chooses the next paper size. The wallet always keeps $3 to $5 for fees. The implemented reserve is $5 unless config is outside that band.
- Eye may halt live trading. Eye must not resume it, and must not change budget, trade size, reserve, one-trade-per-coin, or `size_sol` through a model review.
- Trade size is written only by `choose_trade_usd()` into the live config, not by review JSON.
- A paper entry needs a confirming market: GMGN, DexScreener, or Birdeye. pump.fun and FOMO can add score. They cannot confirm an entry alone.
- One new paper entry per scan. One open position per mint. Cooldown after a buy is 180 minutes.
- Until 30 closes, Eye sizes a fixed $5.50, or $5 when free cash is between $5 and $5.50. After 30 closes, size follows the recent win rate. Free cash under $4, or a computed size under $4, skips the buy.
- When the flat wallet cannot fund a buy above the fee reserve, and the current run has at least one close, Eye refills the paper bank to $50 and keeps the current preset. A bust does not advance the grind index.
- A strategy locks only when the current run has at least 50 closes, the mean return per trade is above 0, and the 95% bootstrap interval’s lower bound is above 0, after the harsh fill costs. Locked rules are not loosened or replaced. The lab may name a shadow-book winner. The desk does not adopt it by itself.
- The dashboard API requires `Authorization: Bearer <DASH_TOKEN>` when that variable is set. The token is stored in the browser as `dash_token`. It is not a user account.
- Secrets (`HELIUS_API_KEY`, `DASH_TOKEN`, `FOMO_API_KEY`, `BIRDEYE_API_KEY`, `ANTHROPIC_API_KEY`, `BUBBLEMAPS_API_KEY`, spend-lock hash and salt) are environment or gitignored files. They are never returned by the API and never written into these documents.

## 2. Roles

| Role | Kind | What it may do |
| --- | --- | --- |
| Operator | Human | Opens the dashboard, reads every screen, connects Phantom, sets the spend lock, allows or disallows wallet trading, approves a Phantom signature. |
| Eye | Paper supervisor | Sizes the next paper buy, grinds or locks strategy, refills a flat paper wallet, researches the public market, reviews rules inside bounds, hires the paper desk, halts live trading. |
| Vet | Paper assistant | Reads the scan and writes one briefing about RugCheck and Bubblemaps. Cannot spend or size. |
| Scan watch | Paper assistant | Reads candidates and tells Eye which names, if any, are clean entries. |
| Scribe | Paper assistant | Reads closed trades and tells Eye whether the book is paying. |
| Risk | Paper assistant | Reads the book. If wallet trading is actually on, it halts live trading. It does not clear a paper-mode halt. |
| Paper engine | System | Scans, scores, opens and manages simulated positions, writes the ledger. |
| Phantom signer | Operator, in the browser | Holds the key. Signs a Jupiter swap only after an explicit Approve click. |

Desk cards (Chief, Scan, Vet, Social, Size, Fills, Risk, Crawler) are a display of current state. They are not extra logins. Social stays off because X and Telegram are not connected. The Eye floor under those cards is the same four assistants at work. It is not a fifth login.

Hiring rejects any assistant whose name contains trade, trader, phantom, spend, spender, size, sizer, wallet, budget, or live. Allowed powers are only `read_scan`, `read_trades`, `write_note`, and `halt_live`. The roster caps at the four assistants above.

## 3. Screens

The app is one page after login. It polls `/api/summary`, `/api/trades?limit=100`, `/api/wallets`, `/api/candidates`, and `/api/eye` every 5 seconds.

### 3.1 Login

Shown when no dashboard token is in local storage, or the API returns 401.

| Field | Required | Notes |
| --- | --- | --- |
| Dashboard token | Yes | Password input. Sent as a bearer token. Not shown again. |

Empty and error states: wrong token clears storage and returns to this screen. A network failure on later screens shows "Can't reach server" and keeps the last good data until the next successful poll.

### 3.2 Shell (all tabs)

Persistent header, desk, feeds, equity, budget, mode banner, and chat.

Header fields:

| Field | Source |
| --- | --- |
| Phase | Scanner status, for example which feeds the current pass is reading |
| SOL price | DexScreener WSOL, CoinGecko fallback. Accepted range $20–$1000. Cache 60 seconds |
| Paper badge | Always shown |
| Phantom control | See section 3.7 |

Desk cards:

| Card | Value | Subtitle |
| --- | --- | --- |
| Chief | Last paper buy symbol, or `none` | last paper pick |
| Scan | Candidate count | how many would enter |
| Vet | RugCheck read count | RugCheck reads |
| Social | `off` | X and Telegram are not connected |
| Size | Current trade USD | free USD above the reserve |
| Fills | Recent buy and sell count | open position count |
| Risk | `halted` or `open` | live cap and whether the spend lock is set |
| Crawler | Count of feeds that returned ok | feed names |

Eye floor, directly under the cards:

| Piece | What it shows |
| --- | --- |
| Header | Phase, last paper pick, and how many of the four assistants are briefing |
| Eye | Boss station. Latest growth sentence, otherwise the strategy line |
| Vet, Scan watch, Scribe, Risk | A station each. A line to Eye while that assistant has a briefing. Waiting stations stay dim |
| Goal, on the Agent tab | “A paper book that pays.” The written briefs, market sentence, and strategy sit under the same diagram |

The floor uses the live book. It does not invent a balance.

Feed chips, each with a state of `live`, `ready`, `link`, `key`, `down`, or `off`:

| Feed | Kind | Live when |
| --- | --- | --- |
| pump.fun | launches | The scan returned rows |
| dexscreener | pairs | The scan returned rows |
| gmgn | wallets | The scan returned rows |
| birdeye | trending | `BIRDEYE_API_KEY` is set and the call succeeds. `key` means the variable is missing |
| rugcheck | rug | A reviewed candidate got a report |
| bubblemap | holders | `BUBBLEMAPS_API_KEY` is set and a map returned. Otherwise `key`. The public map link still opens |
| FOMO | holders | `FOMO_API_KEY` is set and the hourly board returned Solana names |
| Jupiter | swaps | Always `ready`. Used only if the operator approves a live swap |
| Phantom | wallet | `live` only when a public address is linked |
| Solscan | explorer | `link` |
| X, Telegram, Axiom, Robinhood, Dune, TradingView, CoinGlass, CoinMarketCap | various | Hardcoded `off`. A key for these does nothing |

Equity panel: current equity in USD, realized USD, closed-trade count, and a sparkline of cumulative closed SOL PnL for the current run (rows after the last `RESET`).

Stat tiles: win rate, best and worst closed PnL, open count against the cap, trade size, skip count, chase cap, closed PnL.

Budget strip:

| Label | Meaning |
| --- | --- |
| Start | `budget_usd`, default $50 |
| Equity | Mark-to-market of the SOL bank plus open PnL |
| Realized | Closed SOL PnL times SOL price |
| In trades | SOL still in open positions, in USD |
| Free to invest | Equity minus reserve minus capital still in open trades |
| Reserve | Fee reserve, clamped to $3–$5 |
| SOL price | Price used for the conversion |

Banner: in paper mode, Eye picks the size and the reserve stays for fees. If wallet trading is on, the banner says each buy still needs the lock code and a Phantom approval.

### 3.3 Scan

Table of up to 12 candidates.

| Column | Field |
| --- | --- |
| Token | `symbol`, linked to DexScreener |
| Score | Integer score from the rules in section 5 |
| Call | `enter`, `watch`, or `skip` |
| Suggestion | Rule label from closed-trade history: Take, Skip, Pass, Small, Wait |
| Eye | Same history, phrased as a tip for this name |
| Sources | Feed names that mentioned the mint |
| Mcap | USD market cap |
| Liq | USD liquidity |
| 5m | Five-minute percent change |
| Rug | RugCheck label, linked to rugcheck.xyz |
| Map | Bubblemaps cluster percent when a key returned one, otherwise the word `map`. Link is `https://v2.bubblemaps.io/map?address=<mint>&chain=solana`. A stored `chain=sol` is rewritten to `solana` |

Empty state: "First scan still running."

### 3.4 Book

Three tables.

Open positions: token, source label, multiple, fraction left, realized PnL, age in minutes, suggestion, Eye tip.

Recent activity, newest first, up to 40 rows: time, event (`BUY`, `SELL`, `CLOSED`, `SKIP`, `RESET`), mint, multiple, PnL, note, Eye tip.

Tracked wallets: address linked to Solscan, SOL PnL, win rate, trade count, median hold in seconds. Empty until a wallet ranking pass has written `wallets.json`.

### 3.5 Reports

One row per completed 24-hour window: start, end, closed count, win rate, SOL PnL, buy count, narrative text. Hint shows hours until the next report. Empty state names the next timestamp. The clock starts at the first ledger row.

### 3.6 Agent

| Block | Contents |
| --- | --- |
| Eye desk | Goal, Eye as boss, and the four briefing cards. Same staff as the floor, with the full note on each card |
| Agent read | Lesson from the current run once five closes exist |
| Skills | Eight fixed paper checks and when they were last studied |
| Eye | Growth history, improvement tips, learned notes. The written strategy and briefs are on the desk above |
| Agent changes | Time, setting, old value, new value, reason. Empty until Eye has 30 closed trades |

Strategy line is “Keeping strategy N of 4. A bust does not rotate presets.” or “Sticking with this strategy” when locked.

Learned notes are tagged `market` (web) or `own trades`.

### 3.7 Phantom control

Rendered in the header. The browser looks for `window.phantom.solana` or `window.solana.isPhantom`. Only the public address is posted.

| Control | Behavior |
| --- | --- |
| Connect | Stores the public address. Does not turn trading on |
| Set lock | PIN, 4 to 64 characters. Stored as salt plus SHA-256. The PIN stays in React state and is not saved in the repo |
| Allow trades | Requires a correct PIN. Clears a paper-mode halt. Five wrong codes halt with reason `spend lock` |
| Approve | Shown for one pending buy. Builds a Jupiter quote and swap, then `signAndSendTransaction` in the wallet. The server does not auto-sign |

### 3.8 Chat dock

Slide-over. History is the last 40 messages, capped at 80 on disk. The operator asks about PnL, open positions, the 24-hour report, or a token. Answers are composed from the paper book, not from a second trading model. The dock is unavailable until login.

## 4. Data fields

### 4.1 Ledger event

| Field | Type | Notes |
| --- | --- | --- |
| time | datetime string `YYYY-MM-DD HH:MM:SS` | Local time of the process |
| event | enum | `BUY`, `SELL`, `CLOSED`, `SKIP`, `RESET` |
| mint | string | Solana mint. Empty on `RESET` |
| wallet | string | Source label such as `gmgn+dexscreener`, or `paper` on reset |
| price_sol | number | Fill price in SOL |
| x | number | Multiple versus entry. 0 on buys and skips |
| sol_pnl | number | SOL result for this row |
| note | string | Human reason: size, stop, ladder, skip cause, reset |

A current run is every row after the latest `RESET`. Lifetime rows before that reset are history, not the book Eye judges.

### 4.2 Open position

| Field | Type | Notes |
| --- | --- | --- |
| mint | key | One open position per mint |
| symbol | string | From the scan |
| entry | number | Price about 45 seconds after the signal, times one plus slippage |
| left | number | Fraction remaining, starts at 1 |
| tier | integer | Ladder step already sold |
| wallet | string | Source label copied onto the buy |
| t0 | unix time | Opened at, after the delay |
| pnl | number | SOL. Starts at minus the entry fee: 1% of size plus $0.20 |
| size_sol | number | SOL notionally swapped |
| liq_usd | number | Pool liquidity at the fill. Unknown stays 0 and slippage stays 3% |
| last_price | number | Last quoted SOL price |
| last_x | number | Latest multiple, used for equity. Set at the fill so slippage shows immediately |
| misses | integer | Confirmed DexScreener absences. A timeout or HTTP 429 does not increment this |
| stop_armed | boolean | True after price is at the stop. The fill is the next poll, not the stop level. A recovery does not clear it |

A signal that has not filled yet lives only in memory as a pending entry: mint, source, symbol, size, USD, and the signal time. It is dropped on restart. The engine gives up if no price arrives between 45 and 70 seconds, and writes `SKIP` with note `missed the 45s entry price`.

### 4.3 Bank

| Field | Type | Notes |
| --- | --- | --- |
| start_usd | number | 50 |
| start_sol | number | `start_usd / sol_price` at reset |
| realized_sol | number | Sum of closed SOL PnL since reset |

Equity USD is `(start_sol + realized_sol + unrealized SOL) * sol_price`. It moves when the SOL price moves. It is not a USD peg.

### 4.4 Candidate

| Field | Type | Notes |
| --- | --- | --- |
| mint, symbol, name | string | |
| sources | list | Feed names |
| score | number | See section 5 |
| decision | enum | `enter`, `watch`, `skip` |
| note | string | Why |
| mcap, liq | USD | |
| change_5m, change_1h | percent | |
| holders, smart | number | From GMGN when present |
| price_sol, age_min | number | |
| rug, bundler | ratio | GMGN |
| wash | boolean | GMGN wash flag |
| rug_score, rug_label, rug_dangers, holder_pct, rugged | RugCheck | |
| bubble_score, bubble_cluster, bubble_top10, bubble_label, bubble_url | Bubblemaps | |

### 4.5 Eye knowledge

| Field | Type | Notes |
| --- | --- | --- |
| notes[] | date, src (`web` or `trades`), text (max 240), source (max 80) | Newest first. Deduped on exact text |
| last_research, next_research | unix time | Research runs at most once per 24 hours after a success, and retries in 1 hour after a failure |
| market | string | Latest public-scan sentence |
| growth[] | time, closes, recent, win_rate, equity_usd, did, market | Last 30 passes |
| assistants[] | name, job, powers, paper, hired, last, seen | |
| may_hire | boolean | Operator grant. Currently true |

### 4.6 Tune

Bounds Eye and the model may write:

| Setting | Range |
| --- | --- |
| min_sources | 1–3 |
| entry_score | 55–80 |
| max_change_5m | 40–90 |
| max_new_entries_per_scan | 0–1 |
| early_cut_x | 0.70–0.90 |
| early_cut_min | 8–20 |

Also stored: `reviewed_closes`, `changes[]` (time, what, from, to, why), `grind` index, `strategy_locked` and its reason.

Rule changes other than a chase-cap tightening wait for 30 closes. Review, including Anthropic’s settings, waits for the same 30 closes. A hostile research note still blocks loosening `entry_score`, raising `max_change_5m`, or lowering `min_sources`.

The four presets below are named strategies. The grind index is not incremented when the wallet is refilled. A later switch waits until a lab shadow book beats the desk ladder with an interval that excludes zero. The desk does not switch by itself.

Grind presets:

| # | min_sources | entry_score | max_change_5m | early_cut_x | early_cut_min |
| --- | --- | --- | --- | --- | --- |
| 1 | 3 | 70 | 45 | 0.80 | 10 |
| 2 | 3 | 80 | 40 | 0.75 | 8 |
| 3 | 2 | 75 | 55 | 0.85 | 12 |
| 4 | 3 | 65 | 60 | 0.80 | 15 |

### 4.7 Live state

| Field | Notes |
| --- | --- |
| halted, reason | Startup reason is `paper mode` |
| failures | Wrong PIN count. Five halts with `spend lock` |
| stuck_sell | A sell that did not finish |
| exposure_usd, daily_loss_usd, day | Live caps. Defaults: $15 per trade, $45 exposure, $15 daily loss |
| phantom | Public address only |
| wallet_trade | True only after Allow trades |
| lock_salt, lock_hash | Never returned by the API |
| orders[] | id, mint, symbol, usd, side (`buy` or `sell`), frac, why, status (`pending`, `sent`, `failed`), signature, time |
| positions[] | Live inventory after a confirmed buy: mint, symbol, usd, left |
| lab_ready, lab_reason | Whether the lab gate currently allows a live queue. Not a stored secret |

### 4.8 Other stored objects

| Object | Fields |
| --- | --- |
| Wallet rank | wallet, pnl_sol, win_rate, trades, median_hold |
| Report | start, end, closed, buys, skips, wins, win_rate, pnl, best, worst, fades, edits, text |
| Chat message | role (`user` or `agent`), text, time `HH:MM` |
| Study snapshot | chase, thin, young, single counts and the skill lesson text |

## 5. Scoring and exits

Score additions, before hard filters:

| Signal | Points |
| --- | --- |
| pump.fun, DexScreener, Birdeye, or FOMO | 12 each |
| GMGN | 18 |
| Two or more sources | 15 |
| Mint or launchpad is pump.fun | 8 |
| 5-minute change inside the configured band | 20 |
| 5-minute change above the chase cap | −25, then a hard skip |
| Three or more smart wallets | 12, unless Eye's web notes say a copy arrives late. Then the note is `eye: copy arrives late` and the points are not added |
| 80 or more holders | 6 |
| Pair marked live | 4 |
| Liquidity at least twice the minimum | 6 |
| Clean RugCheck score under 15 | 8 |
| Bubblemaps score 60 or higher | 8 |

Hard skips include market cap outside $6,000–$800,000, liquidity under $8,000, no liquidity unless GMGN or DexScreener is present, rug ratio over 0.40, bundler rate over 0.35, wash trading, age under 2 minutes or over 36 hours, too few sources, and the skill and RugCheck or Bubblemaps blocks below.

An `enter` also needs a confirming feed, a 5-minute change inside the band, and a score at or above `entry_score`.

Skills that block an entry:

- 5-minute move over 45%
- Liquidity under 8% of market cap
- Younger than 5 minutes
- Fewer than two sources

RugCheck blocks: rugged flag, a danger name, normalized score 50 or higher, or one wallet holding 35% or more.

Bubblemaps blocks, only when a key is set: largest cluster 20% or more, top 10 clustered wallets 55% or more, or score under 40.

Exits, checked on the price poll:

| Exit | Rule |
| --- | --- |
| Ladder | Sell 40% at 2x, 30% at 3.5x, the rest at 5x |
| Stop | Two polls at or below −35% |
| Time stop | Still under 2x after 90 minutes |
| Early cut | Under `early_cut_x` after `early_cut_min` minutes, once that rule is on |
| Wallet sell | If wallet-follow is on and the copied wallet sells |

Slippage per side is `min(80%, 3% + 2 × trade_usd / pool_liquidity_usd)`. Unknown liquidity stays at 3%. Fee is 1% per side plus $0.20 converted to SOL at the current price. The entry fee is subtracted from realized SOL when the position opens, and it is included in the position PnL so a later `CLOSED` row matches the bank.

Open positions are priced every 12 seconds. A pool that is half the entry liquidity, or less, sells the rest. Three confirmed DexScreener absences close at about 10% of the last price. A stop arms when price is at or below −35% and fills at the next poll’s price.

Eye size, from equity after the $5 reserve. Recent win rate is the last 15 closes:

| Book | Size |
| --- | --- |
| Free cash under $4 | $0, and the buy is skipped |
| Fewer than 30 closes, free cash at least $5.50 | $5.50 |
| Fewer than 30 closes, free cash at least $5 | $5 |
| Fewer than 30 closes, free cash under $5 | $0 |
| Recent win rate under 25% | $4 |
| Recent win rate under 45% | 10% of equity, clamped to $4–$8 |
| Otherwise | 15% of equity, clamped to $6–$12 |

Size never exceeds free cash, and a result under $4 is $0. The buy note reads `SYMBOL size X SOL · $Y phantom paper`. Lock statistics use `sol_pnl / buy size` for closes whose buy note has a parseable size. Closes without that size are left out of the interval.

## 6. Workflows

### 6.1 Scan and paper buy

1. Every 45 seconds the engine reads pump.fun, DexScreener, GMGN, Birdeye, and FOMO. FOMO is cached for 1 hour after success and 10 minutes after an error. A normal FOMO read costs credits, so it must not be polled on the scan interval.
2. Names are merged by mint. Solana FOMO rows use network id `1399811149` and a nested token address. EVM `0x` addresses are ignored.
3. Up to eight names that are not already skipped are sent to RugCheck and, when keyed, Bubblemaps. The score is computed again.
4. Eye tends the wallet, then chooses the USD size.
5. The first `enter` that is not already open and not in cooldown is held as a pending entry. About 45 seconds later the engine prices it. No price by about 70 seconds writes `SKIP` and does not open a position.
6. The delayed fill opens the paper position. If wallet trading is on and the lab gate is open, that fill queues a Phantom buy. The paper fill does not wait for the signature.

### 6.2 Manage an open position

Every 12 seconds the engine prices open mints and applies the ladder, the armed stop, the liquidity drop, the vanish rule, the time stop, and the early cut. A full exit writes `SELL` and then `CLOSED`. Partial ladder sells write `SELL` and leave the position open. A qualifying exit also queues an approve-to-sell order when a live position in that mint still has size left. Nothing is broadcast until the operator approves.

### 6.3 Eye pass

About every 10 minutes, sooner on the first pass if the scan has not posted names:

1. Staff writes briefs.
2. Research runs if it is due. It searches, then fetches one page, and stores 4 to 6 notes. Notes are unverified context. Text inside a note cannot change budget or size.
3. One growth step may raise sources, raise the entry score, turn on the early cut, or tighten the chase cap. While research says the regime is hostile, review must not lower the entry score, widen the 5-minute cap, or reduce the source minimum.
4. Review may adjust settings inside the bounds and may halt live trading. It must not resume live trading.

### 6.4 Bust and refill

When nothing is open, the run has at least one close, and free cash is under $4:

- If 50 or more closes are positive after costs and the 95% interval is above zero, lock the rules, refill to $50, and write `RESET`.
- Otherwise refill to $50 and keep the current preset. A bust does not advance the grind index.

### 6.5 Optional live buy

1. Operator connects Phantom and sets a lock.
2. Operator clicks Allow trades and enters the PIN.
3. A later paper entry queues one pending order under the live USD caps.
4. The header shows Approve. The browser requests a Jupiter quote (`slippageBps` 300) and swap for the SOL mint `So11111111111111111111111111111111111111112`, then asks Phantom to sign and send.
5. The browser posts the signature, or a failure. An empty signature is rejected. A signature is marked sent only after `getSignatureStatuses` says confirmed and `getTransaction` shows the linked wallet gained the mint on a buy, or spent it on a sell.
6. Allow trades stays off until the lab report's `readiness.ready` is true: the desk-ladder book has at least 100 closes over 14 days, a confidence interval above zero, and a random percentile of at least 90. Set `LAB_URL` and `LAB_KEY` on the desk so it can read that report.
7. A paper exit at a ladder, stop, or liquidity drop queues an approve-to-sell order for any live position in that mint. There is no automatic sell.

### 6.6 Daily report

When 24 hours have elapsed since the book origin, or since the previous report, the engine writes one report from ledger rows and tune changes in that window.

### 6.7 Eye floor

On each staff pass, Vet, Scan watch, Scribe, and Risk each write one note if their text changed. The main screen draws those four as stations under Eye. The Agent tab draws the same staff with the goal “A paper book that pays” and the full briefing text. A station with an empty note is Waiting.

### 6.8 Paper Scanner Lab

The lab is a separate process. It reads the desk’s candidate and trade endpoints. It does not send orders, and it does not write the desk’s files or keys. It stores hits, price episodes, and a copy of desk trades, then scores shadow books including `desk-ladder` and `desk-runner`.

`readiness.ready` is true only when `desk-ladder` has at least 100 closes, the episode span is at least 14 days, the confidence-interval low is above 0, and the random percentile is at least 90. The desk reads that report from `LAB_URL` with `LAB_KEY` about every 10 minutes. If either variable is missing, or the report fails, live queueing stays closed. Desk PnL is not the live gate.

## 7. Interfaces

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | Process up |
| GET | `/api/summary` | Equity, desk, budget, open positions, lesson, skills, reports, tune |
| GET | `/api/trades?limit=` | Current-run rows, newest first, with Eye tips |
| GET | `/api/candidates` | Latest scan |
| GET | `/api/wallets` | Ranked wallets |
| GET | `/api/eye` | Knowledge, growth, assistants, strategy |
| GET, POST | `/api/chat` | Read history, send a question |
| GET, POST | `/api/phantom` | Read live state, set address and allow flag |
| POST | `/api/phantom/lock` | Set or change the PIN |
| POST | `/api/phantom/swap` | Return a Jupiter transaction for the pending order. Does not sign it |
| POST | `/api/phantom/done` | Record signature or failure |

Static files are the built dashboard. The API is same-origin in production.

Environment:

| Name | Required | Effect |
| --- | --- | --- |
| `HELIUS_API_KEY` | Yes, to start | Wallet discovery and prices. Placeholder in git is `PASTE_YOUR_HELIUS_API_KEY` |
| `DASH_TOKEN` | Strongly | Locks the API |
| `DATA_DIR` | On the server | State directory. Deployed value `/data` |
| `FOMO_API_KEY` | No | Holder board |
| `BIRDEYE_API_KEY` | No | Trending confirmation. The name must not include a trailing space |
| `ANTHROPIC_API_KEY` | No | Research and review. Model is `EYE_MODEL` or `claude-sonnet-5-5` |
| `BUBBLEMAPS_API_KEY` | No | Holder-cluster scores. The public map link works without it |
| `EYE_MODEL` | No | Research model. Default `claude-sonnet-5-5` |
| `EYE_RESEARCH_HOURS` | No | Hours between successful research passes. Default 24 |
| `LAB_URL`, `LAB_KEY` | No | Lab report used as the live gate. Missing values keep live queueing closed |
| `LIVE_MAX_TRADE_USD`, `LIVE_MAX_EXPOSURE_USD`, `LIVE_DAILY_LOSS_USD` | No | Live caps |
| `PORT` | Platform | HTTP port |

## 8. Acceptance

- With no Phantom connection, paper buys still open and the banner names the reserve.
- A mint on only FOMO or only pump.fun does not get `enter`.
- After a web note that a smart-wallet copy arrives late, candidates say `eye: copy arrives late` and do not gain the 12 smart-wallet points.
- A review that tries to widen `max_change_5m` while a hostile research note is current does not change the value.
- A review JSON that sets `budget_usd`, `trade_usd`, or `entry_score` to a number copied out of a knowledge note is ignored.
- Five wrong lock codes halt live trading. Eye cannot clear that halt.
- Refill writes `RESET`, sets realized SOL to 0, and does not change a linked Phantom address.
- The dashboard token, PIN, and API keys are absent from API responses and from the git commit of these documents.
- The Eye floor shows Eye and the four assistants, and a briefing line moves only while that assistant has a note.
- A public map link uses the mint as `address` and `solana` as `chain`.
- A bust refills to $50 and does not change the grind index.
- A live queue is refused while `LAB_URL` or `LAB_KEY` is unset.

## 9. Out of scope

X, Telegram, Axiom, Robinhood, Dune, TradingView, CoinGlass, and CoinMarketCap are not feeds. Hiring more assistants, unsupervised live trading, and giving the server a private key are out of scope. A creator websocket, an early-entry stream, and automatic adoption of a lab shadow book are out of scope. The paper book does not promise a profit.
