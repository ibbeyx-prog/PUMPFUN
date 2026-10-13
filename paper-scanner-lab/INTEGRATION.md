# Applying a Lab finding to the desk

The Lab only reads `SCANNER_URL`. It does not write `trades.csv`, `bank.json`, `agent_tune.json`, `config.json`, or `.env`. Nothing in a report changes the live or paper book until you edit the desk yourself.

Wait until the sample line says `meaningful` (100 coins) before treating a ranking as a clue, and `trustworthy` (300 coins) before changing a rule. A verdict of `too few trades to tell` or `not distinguishable from luck` means leave the desk alone.

## What the nine books are

Each book sees the same recorded snapshots. Entry rules differ by column. Exit rules differ by row.

| | Cut fast | Ladder | Hold |
| --- | --- | --- | --- |
| Strict: 3 sources, score 80, 5m cap 40 | `strict-cut` | `strict-ladder` | `strict-hold` |
| Desk: 3 sources, score 70, 5m cap 45 | `desk-cut` | `desk-ladder` | `desk-hold` |
| Loose: 2 sources, score 65, 5m cap 60 | `loose-cut` | `loose-ladder` | `loose-hold` |

`desk-ladder` is the closest replay of the current paper desk: ladder at 2x / 3.5x / 5x, stop at −35% on two prints, early cut at 0.8x after 10 minutes, time stop at 90 minutes under 2x. Fills in the Lab are harsher than the desk on purpose, so a Lab loss does not have to match the desk's SOL PnL. Compare books with each other, not with the desk's dollar equity.

All nine still refuse a hard skip: rug, wash, bundled, thin liquidity, market cap outside $6k–$800k, too new, too old, or no liquidity. They also require a confirming feed (GMGN, DexScreener, or Birdeye), a 5-minute change of at least 5%, and an age of at least 5 minutes when age is known.

## If one book ranks first

Only promote it when its 95% interval is above zero (`beats zero`) and its random percentile is high (a score of 95 means it beat 95% of same-sized random samples from the same coins).

Then, on the desk, change only the matching tune fields. Eye's bounds are the limit:

| Lab rule | Desk field | Allowed range |
| --- | --- | --- |
| Source minimum | `min_sources` | 1–3 |
| Score floor | `entry_score` | 55–80 |
| 5-minute cap | `max_change_5m` | 40–90 |
| Early-cut multiple | `early_cut_x` | 0.70–0.90 |
| Early-cut wait | `early_cut_min` | 8–20 |

Do not change `budget_usd`, `trade_usd`, `reserve_usd`, or the one-trade-per-coin rule from a Lab report. Eye sizes trades itself, and the fee reserve stays $3–$5.

The grind presets live in `PRESETS` in `eye.py`. A winning Lab column is a candidate for the next preset, not an automatic overwrite. If `strategy_locked` is set, the desk has already decided to keep the current run's rules. Do not unlock it from the Lab.

## If the outcome tables disagree with the desk

- Skips that make money in the forward column are rules that may be too tight. Read the skip-reason table before lowering a filter. A rug skip that happens to bounce is not a reason to drop RugCheck.
- High scores that lose mean the score is not a reason to loosen entries.
- One-source rows that lose support leaving `min_sources` at 2 or 3.

## If the desk-loss counts pile up

| Label | What it means | Desk place to look |
| --- | --- | --- |
| rug | Close at 0.35x or worse, or a rug note | RugCheck blocks in `checks.py`. Bubblemaps stays off until `BUBBLEMAPS_API_KEY` is set |
| gave back gains | A sell printed at 1.5x or more and the close came back under 1.2x | Ladder fractions in `config.json` |
| sold too early | An agent cut, or the lab later saw 2x after a weak exit | `early_cut_x` and `early_cut_min` |
| slow bleed | A loss that is none of the above, usually the time stop | `time_stop_min` |

## Hypotheses

Sentences under "Hypotheses (not findings)" come from `ANTHROPIC_API_KEY` when it is set. They are not measurements. Do not paste them into `agent_tune.json`.

## Clock

`LEDGER_TZ_OFFSET_H` only affects how the Lab reads the desk's naive ledger times. It does not change the desk. Use `0` when the Lab and the desk run in the same timezone.
