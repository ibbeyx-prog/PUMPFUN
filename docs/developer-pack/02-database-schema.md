# Database schema: Paper Scanner

The running app stores one book as files in `DATA_DIR`: `trades.csv`, `state.json`, `bank.json`, `eye_knowledge.json`, `agent_tune.json`, `live_state.json`, `reports.json`, `chat.json`, `wallets.json`, and `study.json`. This schema is the relational equivalent. It is one deployment, one paper book, and one operator. Do not store API keys, the dashboard token, or the spend-lock PIN in these tables. Those stay in a secret manager. The lock is stored only as salt and hash.

Types below are PostgreSQL. Money that is SOL or a ratio uses `numeric`. USD amounts that are displayed to cents can use `numeric(12,2)`. Timestamps are `timestamptz` in UTC. New desk rows are written as UTC `YYYY-MM-DDTHH:MM:SSZ`. Older ledger rows are local `YYYY-MM-DD HH:MM:SS` and must still parse. The screen converts either form for display.

## 1. Operator and secrets

The dashboard has one shared bearer token, not a user table of passwords. The operator row exists so Phantom, the lock, and chat have an owner.

```sql
create table operator (
  id              smallint primary key default 1 check (id = 1),
  display_name    text not null default 'Operator',
  created_at      timestamptz not null default now()
);

create table secret_ref (
  id              smallint primary key default 1 check (id = 1),
  helius_set      boolean not null default false,
  dash_token_set  boolean not null default false,
  fomo_set        boolean not null default false,
  birdeye_set     boolean not null default false,
  anthropic_set   boolean not null default false,
  bubblemaps_set  boolean not null default false,
  lab_url_set     boolean not null default false,
  lab_key_set     boolean not null default false,
  eye_model       text not null default 'claude-sonnet-5-5'
);
```

`secret_ref` records only whether a secret is configured. The value lives outside the database.

## 2. Settings

```sql
create table book_config (
  id                          smallint primary key default 1 check (id = 1),
  budget_usd                  numeric(12,2) not null default 50,
  trade_usd                   numeric(12,2) not null default 5.50,
  reserve_usd                 numeric(12,2) not null default 5,
  one_trade_per_coin          boolean not null default true,
  size_sol                    numeric(18,8) not null default 0.1,
  max_open_positions          integer not null default 5,
  max_chase_pct               numeric(8,4) not null default 0.25,
  sim_slippage                numeric(8,4) not null default 0.03,
  slip_impact                 numeric(8,4) not null default 2,
  slip_cap                    numeric(8,4) not null default 0.80,
  fee_pct                     numeric(8,4) not null default 0.01,
  flat_fee_usd                numeric(12,2) not null default 0.20,
  entry_delay_sec             integer not null default 45,
  entry_giveup_sec            integer not null default 70,
  position_poll_sec           integer not null default 12,
  fee_sol                     numeric(18,8) not null default 0.002,
  stop_loss_pct               numeric(8,4) not null default 0.35,
  time_stop_min               integer not null default 90,
  follow_wallet_sells         boolean not null default true,
  price_poll_sec              integer not null default 3,
  scan_sec                    integer not null default 45,
  entry_score                 integer not null default 70,
  max_new_entries_per_scan    integer not null default 1,
  entry_cooldown_min          integer not null default 180,
  min_liquidity_usd           numeric(14,2) not null default 8000,
  min_mcap_usd                numeric(14,2) not null default 500000,
  max_mcap_usd                numeric(14,2) not null default 0,
  min_change_5m               numeric(8,2) not null default 5,
  max_change_5m               numeric(8,2) not null default 90,
  max_rug_ratio               numeric(8,4) not null default 0.40,
  max_bundler_rate            numeric(8,4) not null default 0.35,
  min_age_min                 integer not null default 2,
  max_age_hours               integer not null default 36,
  live_max_trade_usd          numeric(12,2) not null default 15,
  live_max_exposure_usd       numeric(12,2) not null default 45,
  live_daily_loss_usd         numeric(12,2) not null default 15
);

create table ladder_tier (
  step        integer primary key,
  multiple_x  numeric(8,2) not null,
  sell_frac   numeric(8,4) not null check (sell_frac > 0 and sell_frac <= 1)
);
```

Seed `ladder_tier` with `(1, 2.0, 0.40)`, `(2, 3.5, 0.30)`, `(3, 5.0, 1.00)`.

`budget_usd`, `trade_usd`, `reserve_usd`, `one_trade_per_coin`, and `size_sol` are locked against Eye's model review. `trade_usd` defaults to 5.50 and is overwritten by Eye's sizer on every scan. `entry_score` defaults to 70, matching grind preset 1. `fee_sol` and `price_poll_sec` are deprecated: the running fill uses `fee_pct` plus `flat_fee_usd`, and open positions use `position_poll_sec`. Slippage is `sim_slippage` plus `slip_impact` against pool liquidity, capped by `slip_cap`. The reserve stored here is 5. Sizing clamps any other value into $3–$5, so the running book stays at $5.

## 3. Bank, runs, and ledger

```sql
create table paper_run (
  id            bigint generated always as identity primary key,
  started_at    timestamptz not null default now(),
  start_usd     numeric(12,2) not null,
  start_sol     numeric(18,8) not null,
  sol_price     numeric(12,4) not null,
  grind_index   integer not null default 0,
  locked        boolean not null default false,
  lock_reason   text not null default ''
);

create table bank (
  id              smallint primary key default 1 check (id = 1),
  run_id          bigint not null references paper_run(id),
  start_usd       numeric(12,2) not null,
  start_sol       numeric(18,8) not null,
  realized_sol    numeric(18,8) not null default 0
);

create table ledger (
  id          bigint generated always as identity primary key,
  run_id      bigint not null references paper_run(id),
  at          timestamptz not null,
  event       text not null check (event in ('BUY','SELL','CLOSED','SKIP','RESET')),
  mint        text not null default '',
  source      text not null default '',
  price_sol   numeric(24,12) not null default 0,
  multiple_x  numeric(12,4) not null default 0,
  sol_pnl     numeric(18,8) not null default 0,
  note        text not null default ''
);

create index ledger_run_at on ledger (run_id, at);
create index ledger_mint on ledger (mint, event);
```

`source` is the current `wallet` column: a `+`-joined feed list, or `paper` on reset. A new run starts on `RESET`. Eye's win rate, lock test, and sizing read only the open run.

```sql
create table position (
  mint        text primary key,
  run_id      bigint not null references paper_run(id),
  symbol      text not null default '',
  source      text not null default '',
  entry_sol   numeric(24,12) not null,
  size_sol    numeric(18,8) not null,
  left_frac   numeric(8,6) not null default 1,
  tier        integer not null default 0,
  opened_at   timestamptz not null,
  pnl_sol     numeric(18,8) not null,
  liq_usd     numeric(16,2) not null default 0,
  last_price  numeric(24,12),
  last_x      numeric(12,4),
  misses      integer not null default 0,
  stop_armed  boolean not null default false,
  check (left_frac >= 0 and left_frac <= 1)
);

create table pending_entry (
  mint        text primary key,
  run_id      bigint not null references paper_run(id),
  symbol      text not null default '',
  source      text not null default '',
  size_sol    numeric(18,8) not null,
  trade_usd   numeric(12,2) not null,
  signaled_at timestamptz not null
);
```

`pending_entry` is memory in the current process and is empty after a restart. A database may persist it, but a row older than `entry_giveup_sec` must become a `SKIP`, not a fill. Deleting a `position` row is the close. The `CLOSED` ledger row remains. `pnl_sol` on open already includes the entry fee.

## 4. Scan

```sql
create table scan (
  id          bigint generated always as identity primary key,
  at          timestamptz not null default now(),
  sol_usd     numeric(12,4),
  phase       text not null default ''
);

create table scan_source (
  scan_id     bigint not null references scan(id) on delete cascade,
  name        text not null,
  ok          boolean not null,
  n           integer not null default 0,
  error       text not null default '',
  primary key (scan_id, name)
);

create table candidate (
  id              bigint generated always as identity primary key,
  scan_id         bigint not null references scan(id) on delete cascade,
  mint            text not null,
  symbol          text not null default '',
  name            text not null default '',
  score           integer not null,
  decision        text not null check (decision in ('enter','watch','skip')),
  note            text not null default '',
  mcap_usd        numeric(16,2),
  liq_usd         numeric(16,2),
  change_5m       numeric(10,2),
  change_1h       numeric(10,2),
  holders         integer,
  smart_wallets   integer,
  price_sol       numeric(24,12),
  age_min         numeric(10,2),
  rug_ratio       numeric(8,4),
  bundler_rate    numeric(8,4),
  wash            boolean not null default false,
  pump            boolean not null default false,
  live_pair       boolean not null default false,
  rug_score       numeric(8,2),
  rug_label       text not null default '',
  holder_pct      numeric(8,2),
  bubble_score    numeric(8,2),
  bubble_cluster  numeric(8,4),
  bubble_top10    numeric(8,4),
  bubble_label    text not null default '',
  bubble_url      text not null default '',
  unique (scan_id, mint)
);

create table candidate_source (
  candidate_id  bigint not null references candidate(id) on delete cascade,
  source        text not null,
  primary key (candidate_id, source)
);
```

Keep the latest scan for the screen. Older scans can be pruned. FOMO's own cache is not a table: one successful read per hour is an external quota, enforced in the scanner.

## 5. Eye, assistants, and tune

```sql
create table eye_note (
  id          bigint generated always as identity primary key,
  at          timestamptz not null default now(),
  src         text not null check (src in ('web','trades')),
  text        text not null check (char_length(text) <= 240),
  source      text not null default '' check (char_length(source) <= 80),
  unique (text)
);

create table eye_state (
  id              smallint primary key default 1 check (id = 1),
  last_research   timestamptz,
  next_research   timestamptz,
  market          text not null default '',
  may_hire        boolean not null default true
);

create table eye_growth (
  id            bigint generated always as identity primary key,
  at            timestamptz not null default now(),
  closes        integer not null,
  recent        integer not null,
  win_rate      numeric(6,4),
  equity_usd    numeric(12,2),
  did           text not null,
  market        text not null default ''
);

create table assistant (
  name      text primary key,
  job       text not null,
  paper     boolean not null default true,
  hired_at  timestamptz not null default now(),
  last_text text not null default '',
  seen_at   timestamptz
);

create table assistant_power (
  assistant_name  text not null references assistant(name) on delete cascade,
  power           text not null check (power in ('read_scan','read_trades','write_note','halt_live')),
  primary key (assistant_name, power)
);

create table tune_value (
  name    text primary key,
  value   numeric(12,4) not null,
  check (name in (
    'min_sources','entry_score','max_change_5m',
    'max_new_entries_per_scan','early_cut_x','early_cut_min'
  ))
);

create table tune_state (
  id                smallint primary key default 1 check (id = 1),
  reviewed_closes   integer not null default 0,
  grind_index       integer not null default 0,
  strategy_locked   boolean not null default false,
  lock_reason       text not null default '',
  entry_rule        text not null default ''   -- 'two-source' once ensure_entry_rule() has run
);

create table tune_change (
  id        bigint generated always as identity primary key,
  at        timestamptz not null default now(),
  what      text not null,
  old_value text not null default '',
  new_value text not null default '',
  why       text not null default ''
);

create table grind_preset (
  preset_no       integer primary key check (preset_no between 1 and 4),
  min_sources     integer not null,
  entry_score     integer not null,
  max_change_5m   integer not null,
  early_cut_x     numeric(4,2) not null,
  early_cut_min   integer not null
);
```

Seed `grind_preset` with the four rows in the requirements. A refill must not increment `grind_index`. Application code must still clamp writes to the bounds in section 4.6 of the requirements, and must reject locked-field names. `tune_value` writes from review wait until the open run has 100 `CLOSED` rows, except a chase-cap tightening.

## 6. Live wallet

```sql
create table live_guard (
  id                smallint primary key default 1 check (id = 1),
  halted            boolean not null default true,
  reason            text not null default 'paper mode',
  pin_failures      integer not null default 0,
  stuck_sell        boolean not null default false,
  exposure_usd      numeric(12,2) not null default 0,
  daily_loss_usd    numeric(12,2) not null default 0,
  loss_day          date,
  phantom_address   text not null default '',
  wallet_trade      boolean not null default false,
  lock_salt         text,
  lock_hash         text
);

create table live_order (
  id          bigint generated always as identity primary key,
  at          timestamptz not null default now(),
  mint        text not null,
  symbol      text not null default '',
  usd         numeric(12,2) not null default 0,
  side        text not null default 'buy' check (side in ('buy','sell')),
  frac        numeric(8,6),
  why         text not null default '',
  status      text not null check (status in ('pending','sent','failed')),
  signature   text not null default ''
);

create table live_position (
  mint    text primary key,
  symbol  text not null default '',
  usd     numeric(12,2) not null,
  left_frac numeric(8,6) not null default 1
);
```

`lock_salt` and `lock_hash` are excluded from every API view. `phantom_address` is the public key only. `signature` is the chain signature returned by the browser. An empty signature cannot set `sent`. `sent` also requires `getSignatureStatuses` confirmed or finalized, and `getTransaction` showing the linked wallet gained the mint on a buy or spent it on a sell. A confirmed buy inserts or updates `live_position`. A confirmed sell reduces `left_frac`.

Planned, not built (gap report G1 and G4). Add these before live money:

```sql
create table live_audit (
  id        bigint generated always as identity primary key,
  at        timestamptz not null default now(),
  action    text not null check (action in ('connect','allow','halt','resume','lock_set','lock_change','lock_fail')),
  actor     text not null check (actor in ('operator','eye','risk','system')),
  reason    text not null default '',
  outcome   text not null default ''
);

create table fill_quote (
  id              bigint generated always as identity primary key,
  at              timestamptz not null default now(),
  mint            text not null,
  side            text not null check (side in ('buy','sell')),
  usd             numeric(12,2) not null,
  paper_price_sol numeric(24,12),
  quote_price_sol numeric(24,12),
  price_impact    numeric(8,4),
  live_order_id   bigint references live_order(id),
  fill_price_sol  numeric(24,12)
);
```

`fill_quote` holds a Jupiter quote beside each paper fill, and the confirmed fill once live. A buy whose `price_impact` is over 0.05 is refused. `live_audit` never stores the PIN or any key.

## 7. Reports, chat, wallets, study

```sql
create table report (
  id          bigint generated always as identity primary key,
  window_start timestamptz not null,
  window_end   timestamptz not null,
  closed      integer not null,
  buys        integer not null,
  skips       integer not null,
  wins        integer not null,
  win_rate    numeric(6,4),
  pnl_sol     numeric(18,8) not null,
  best_sol    numeric(18,8),
  worst_sol   numeric(18,8),
  fades       integer not null default 0,
  text        text not null,
  unique (window_start)
);

create table report_edit (
  report_id   bigint not null references report(id) on delete cascade,
  edit        text not null
);

create table chat_message (
  id      bigint generated always as identity primary key,
  at      timestamptz not null default now(),
  role    text not null check (role in ('user','agent')),
  text    text not null
);

create table tracked_wallet (
  address       text primary key,
  pnl_sol       numeric(18,8) not null,
  win_rate      numeric(6,4),
  trades        integer not null,
  median_hold_sec integer not null,
  ranked_at     timestamptz not null default now()
);

create table study_snapshot (
  id          bigint generated always as identity primary key,
  at          timestamptz not null default now(),
  names       integer not null,
  chasing     integer not null,
  thin        integer not null,
  young       integer not null,
  single      integer not null,
  rug_hits    integer not null default 0,
  bubble_hits integer not null default 0,
  note        text not null default ''
);
```

Chat retention is the latest 80 messages. Wallet rows are replaced on each ranking pass.

## 8. File mapping

| File today | Tables |
| --- | --- |
| `trades.csv` | `ledger` |
| `state.json` | `position`, `pending_entry` |
| `bank.json` | `bank`, `paper_run` |
| `eye_knowledge.json` | `eye_note`, `eye_state`, `eye_growth`, `assistant`, `assistant_power` |
| `agent_tune.json` | `tune_value`, `tune_state`, `tune_change` |
| `live_state.json` | `live_guard`, `live_order`, `live_position` |
| `reports.json` | `report`, `report_edit` |
| `chat.json` | `chat_message` |
| `wallets.json` | `tracked_wallet` |
| `study.json` | `study_snapshot` |
| `quotes.csv` | `paper_quote` |
| `config.json` non-secret keys | `book_config`, `ladder_tier` |
| `backups/YYYY-MM-DD/` | None. A nightly database dump replaces it |

Files are written atomically today (temp file, then rename), and copied once per UTC day into `backups/`. A database port should keep both guarantees with transactions and a scheduled dump that is restored at least once as a test.

## 9. Integrity rules the application must keep

- At most one open `position` per mint, and at most one pending `live_order`.
- `reserve_usd` is clamped to the closed interval from 3 to 5 before sizing.
- A buy is refused when free USD above the reserve is under 4, or when the chosen size is under 4.
- A refill (`RESET` plus a new `paper_run`) is allowed only when no `position` is open, the run has at least one `CLOSED` row, and the sizing rule returns under $4 for the next buy. The refill test and the sizing rule must be the same function, so no balance is left that can neither trade nor refill.
- `tune_state.entry_rule = 'two-source'` is written once with three `tune_change` rows (`min_sources` 2, `entry_score` 65, `max_change_5m` 60). It is never written while `strategy_locked` is true.
- `RESET` inserts a ledger row and a new `paper_run`, zeroes `realized_sol`, and deletes open positions. It does not change `live_guard.phantom_address`.
- Strategy lock requires at least 50 sized `CLOSED` rows in the open run, a mean of `sol_pnl / buy size` above 0, and a 95% bootstrap lower bound above 0. Unsizable closes are excluded from that test.
- Sizing before 30 closes is $5.50, or $5 when free cash is in `[$5, $5.50)`, else $0. After 30 closes, size uses the win rate of the latest 15 closes, still never above free cash and never under $4.
- Model output may update `tune_value` only inside bounds, and only when `strategy_locked` is false. Hostile web notes additionally forbid lowering `entry_score`, raising `max_change_5m`, or lowering `min_sources`.
- Assistant names that match the denied words in the requirements are rejected before insert.

## 10. Paper Scanner Lab

The lab is a second database. It is not the paper book. SQLite today, under the lab’s own `DATA_DIR`. Times in the running file are unix seconds. A PostgreSQL port should use `timestamptz`.

```sql
create table lab_hit (
  id          bigint generated always as identity primary key,
  scanned_at  timestamptz not null,
  recorded_at timestamptz not null,
  mint        text not null,
  symbol      text not null default '',
  score       numeric(8,2),
  decision    text not null default '',
  note        text not null default '',
  sources     jsonb not null default '[]',
  mcap_usd    numeric(16,2),
  liq_usd     numeric(16,2),
  change_5m   numeric(10,2),
  price_sol   numeric(24,12),
  age_min     numeric(10,2),
  rug_label   text not null default '',
  features    jsonb not null default '{}'
);

create table lab_episode (
  id          bigint generated always as identity primary key,
  mint        text not null,
  symbol      text not null default '',
  started_at  timestamptz not null,
  track_until timestamptz not null,
  score       numeric(8,2),
  decision    text not null default '',
  note        text not null default '',
  sources     jsonb not null default '[]',
  mcap_usd    numeric(16,2),
  liq_usd     numeric(16,2),
  change_5m   numeric(10,2),
  age_min     numeric(10,2),
  rug_label   text not null default '',
  features    jsonb not null default '{}',
  last_priced timestamptz,
  done        boolean not null default false
);

create table lab_price (
  episode_id  bigint not null references lab_episode(id) on delete cascade,
  at          timestamptz not null,
  price_sol   numeric(24,12) not null,
  primary key (episode_id, at)
);

create table lab_desk_trade (
  id          bigint generated always as identity primary key,
  time_text   text not null default '',
  event       text not null default '',
  mint        text not null default '',
  source      text not null default '',
  price_sol   numeric(24,12),
  multiple_x  numeric(12,4),
  sol_pnl     numeric(18,8),
  note        text not null default ''
);

create table lab_meta (
  k  text primary key,
  v  text not null
);
```

Research-book results (twenty ids `{entry}-{exit}`, entries strict, desk, loose, looser, filters and exits ladder, cut, runner, wide), `desk-ladder-real`, nine ticket rows (`{entry}-ladder-5.5`, `-8`, `-12` for the top three entry rules), and the `hold-sol` and `buy-every-name` baselines are computed from episodes and prices. They are a report, not rows the desk writes back. The live gate reads `desk-ladder-real` closes, the span from the earliest to latest `started_at`, the interval low, and the random percentile.

`lab_meta` keys in use: `last_scanned_at`; `frozen_picks`, JSON `{at, picks, tried, explore}` written once, four hours after `LAB_FREEZE_AT`, and never rewritten; `desk_quotes`, the desk's `/api/quotes` summary without rows plus `fetched_at`.

Desk quote log, `DATA_DIR/quotes.csv` today (included in the daily backup):

```sql
create table paper_quote (
  id          bigint generated always as identity primary key,
  at          timestamptz not null,
  side        text not null check (side in ('buy','sell')),
  mint        text not null,
  usd         numeric(12,2),
  paper_px    numeric(24,12),            -- SOL per token after paper slippage, before the 1% fee
  quote_px    numeric(24,12),            -- SOL per token from the Jupiter quote
  gap         numeric(10,6),             -- positive means the real route was worse than paper
  impact      numeric(12,8),
  route       text not null default '',
  status      text not null check (status in ('ok','no_route','error')),
  error       text not null default ''
);
```
