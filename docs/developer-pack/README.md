# Paper Scanner developer pack

Handoff for the PUMPFUN paper-trading desk. These documents describe the system as it runs today: one operator, one paper book, Eye as the boss of five assistants (including Scout for strategy research), a separate Paper Scanner Lab that never trades, and Phantom as an optional browser signer. The server never receives a wallet private key.

| Document | Use |
| --- | --- |
| [Developer requirements](01-developer-requirements.md) | Screens, roles, fields, and workflows |
| [Database schema](02-database-schema.md) | Tables and columns for a relational store |
| [User stories](03-user-stories.md) | Stories from each role, ready for a backlog |

Stories marked `now` describe the running desk. Stories marked `next` come from the October 13 gap report; the ones tied to G1 to G6 must ship before any live money.

Current state, Oct 14, 2026: the desk runs `main` at `f89d91d` on the two-source paper entry, logs a Jupiter quote beside every paper fill, and reads the lab report (`LAB_URL` and `LAB_KEY` are set). The lab scores twenty research books plus `desk-ladder-real`, and prints a weekly verdict. The explore week runs Oct 15 to 21, the confirm week Oct 22 to 28, and the verdict lands Oct 28. Live trading is off and its gate is closed. See section 7a of the requirements for the full deployed state.

Checks a developer can run with no network: `python paper-scanner-lab/selftest.py` and `python paper-scanner-lab/parity_check.py` (the lab's fills against the desk's own paper code, within $0.01).

Runtime today is files under `DATA_DIR` (local directory, or `/data` on the deployed service). The schema is the target model if that store is moved to a database. Do not copy secrets from `config.json` or `.env` into tickets.
