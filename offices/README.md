# offices/
Reusable, state-agnostic office types. Each folder holds:
- `powers.yaml` — the office's powers, each with a stable ID (e.g. `P-BUDGET`) and a source.
- `survey.yaml` — hypothetical scenarios; every scenario lists the power IDs it rests on.

State-specific differences go in `data/states/<st>/office-overrides/<office-type>.yaml`, citing the statute.
