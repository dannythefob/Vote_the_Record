# src/
Code only. No data files here.
- `collectors/` — one module per source type (Legistar, Congress.gov, FEC); state-specific adapters under `collectors/states/<st>/`.
- `validate/` — enforces CLAUDE.md rules 2–5 against `schemas/`.
- `build/` — renders voter guides from `data/` and `offices/`.
