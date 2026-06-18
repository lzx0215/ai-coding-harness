# Generic CLI Agent Adapter

Generic CLI agents must receive explicit input files and return structured output files.

They must not mutate Harness state directly.

Required result fields:

- status
- summary
- findings
- evidence
- not_tested
- residual_risks
