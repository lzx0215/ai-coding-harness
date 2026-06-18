# Risks

| Risk | Impact | Mitigation |
| --- | --- | --- |
| External reviewer mutates state | Breaks audit boundary | Claude Code is read-only and returns evidence only. |
| Review timeout treated as pass | False completion | `timeout` maps to `review_timeout`, never `reviewed`. |
| Rules become too heavy | Agent overhead | `AGENTS.md` stays lean; details live in `harness/core`. |
