# Paper Scanner Lab

A read-only sidecar for the Paper Scanner desk. It never trades and never touches the desk's files or keys. It reads the desk's API, records every scanned coin (including skips), prices each for 4 hours, and replays your rules on that history so you can see what actually works.

## What it answers

- Do score, source count and skip rules predict anything? (outcomes by decision / score / sources / skip reason)
- Which preset or exit style does best on the SAME signals? (9 shadow books, run in parallel)
- Does a strategy beat random entries from the same list? (random baseline percentile)
- Is a result distinguishable from luck? (95% bootstrap CI, small-sample verdicts)
- Why did the desk's real paper trades lose? (rug / gave back gains / slow bleed / sold too early)

Fills are harsher than the desk's: slippage grows with size/liquidity, 1% fee per side, $0.20 per transaction, 45s entry delay, vanished tokens count as ~90% loss.

## Run locally (PowerShell)

```powershell
cd paper-scanner-lab
pip install -r requirements.txt
$env:SCANNER_URL="https://your-desk.up.railway.app"
$env:DASH_TOKEN="the desk's dashboard token"
$env:LAB_KEY="pick-a-password"
python lab.py serve          # open http://localhost:8090/?key=pick-a-password
```

Other commands: `python lab.py collect` (collector only), `python lab.py report` (print the report), `python selftest.py` (checks the engine on a synthetic market).

## Deploy on Railway (second service)

New service from this folder (Dockerfile is detected). Variables: `SCANNER_URL`, `DASH_TOKEN`, `LAB_KEY`, optional `ANTHROPIC_API_KEY` (adds AI-written hypotheses, labeled as hypotheses). Add a Volume at `/data`. Reports are meaningful after about 2 days (100+ coins) and trustworthy after 1–2 weeks (300+).

## Notes

If your desk's `/api/candidates` uses other field names, edit `record_scan()` in `lab.py`.

Ledger times are the desk's local time; set `LEDGER_TZ_OFFSET_H` if the desk's timezone differs from the Lab's. The value is hours added to those naive timestamps. Leave it at `0` when both clocks match.

The Lab cannot change the desk. Apply what it finds with `INTEGRATION.md`.
