# Paper Scanner developer pack

Handoff for the PUMPFUN paper-trading desk. These documents describe the system as it runs today: one operator, one paper book, Eye as the paper supervisor, and Phantom as an optional browser signer. The server never receives a wallet private key.

| Document | Use |
| --- | --- |
| [Developer requirements](01-developer-requirements.md) | Screens, roles, fields, and workflows |
| [Database schema](02-database-schema.md) | Tables and columns for a relational store |
| [User stories](03-user-stories.md) | Stories from each role, ready for a backlog |

Runtime today is files under `DATA_DIR` (local directory, or `/data` on the deployed service). The schema is the target model if that store is moved to a database. Do not copy secrets from `config.json` or `.env` into tickets.
