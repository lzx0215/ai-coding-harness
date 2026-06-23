## init owning run A
```powershell
python -m harness.cli init-run harness\runs\2026-06-23-phase-9a-cross-run-local-queue\live-smoke\owning-run-a --run-id phase9a-live-owning-run-a --track Standard --workflow standard-agent-adapter-change --base-commit acba379a930232a4d187462ae51ff4263f15a496
```

Output:
```text
initialized run: phase9a-live-owning-run-a -> draft
exit=0
```

## init owning run B
```powershell
python -m harness.cli init-run harness\runs\2026-06-23-phase-9a-cross-run-local-queue\live-smoke\owning-run-b --run-id phase9a-live-owning-run-b --track Standard --workflow standard-agent-adapter-change --base-commit acba379a930232a4d187462ae51ff4263f15a496
```

Output:
```text
initialized run: phase9a-live-owning-run-b -> draft
exit=0
```

## queue run-local job A
```powershell
python -m harness.cli queue-generic-agent harness\runs\2026-06-23-phase-9a-cross-run-local-queue\live-smoke\owning-run-a job-a --agent generic-test-agent -- python -c import json, os; from pathlib import Path; payload={'run_id':os.environ['HARNESS_RUN_ID'],'job_id':os.environ['HARNESS_JOB_ID'],'agent':os.environ['HARNESS_AGENT'],'adapter':os.environ['HARNESS_AGENT_ADAPTER'],'status':'passed','summary':'phase9a cross-run queue live smoke passed','findings':[],'evidence':[],'not_tested':[],'residual_risks':[],'generated_at':'2026-06-23T00:00:00Z'}; Path(os.environ['HARNESS_AGENT_OUTPUT_FILE']).write_text(json.dumps(payload, indent=2)+'\n', encoding='utf-8')
```

Output:
```text
queued generic-agent: phase9a-live-owning-run-a/job-a
exit=0
```

## queue run-local job B
```powershell
python -m harness.cli queue-generic-agent harness\runs\2026-06-23-phase-9a-cross-run-local-queue\live-smoke\owning-run-b job-b --agent generic-test-agent -- python -c import json, os; from pathlib import Path; payload={'run_id':os.environ['HARNESS_RUN_ID'],'job_id':os.environ['HARNESS_JOB_ID'],'agent':os.environ['HARNESS_AGENT'],'adapter':os.environ['HARNESS_AGENT_ADAPTER'],'status':'passed','summary':'phase9a cross-run queue live smoke passed','findings':[],'evidence':[],'not_tested':[],'residual_risks':[],'generated_at':'2026-06-23T00:00:00Z'}; Path(os.environ['HARNESS_AGENT_OUTPUT_FILE']).write_text(json.dumps(payload, indent=2)+'\n', encoding='utf-8')
```

Output:
```text
queued generic-agent: phase9a-live-owning-run-b/job-b
exit=0
```

## queue cross-run entry A
```powershell
python -m harness.cli queue-cross-run-job harness\runs\2026-06-23-phase-9a-cross-run-local-queue\live-smoke\cross-run-queue entry-a --run-dir harness\runs\2026-06-23-phase-9a-cross-run-local-queue\live-smoke\owning-run-a --job-id job-a --creator codex --worker-group local
```

Output:
```text
queued cross-run job: cross-run-queue/entry-a -> phase9a-live-owning-run-a/job-a
exit=0
```

## queue cross-run entry B
```powershell
python -m harness.cli queue-cross-run-job harness\runs\2026-06-23-phase-9a-cross-run-local-queue\live-smoke\cross-run-queue entry-b --run-dir harness\runs\2026-06-23-phase-9a-cross-run-local-queue\live-smoke\owning-run-b --job-id job-b --creator codex --worker-group local
```

Output:
```text
queued cross-run job: cross-run-queue/entry-b -> phase9a-live-owning-run-b/job-b
exit=0
```

## run local cross-run queue once
```powershell
python -m harness.cli run-cross-run-queue harness\runs\2026-06-23-phase-9a-cross-run-local-queue\live-smoke\cross-run-queue --once --worker-id phase9a-local-worker --worker-group local
```

Output:
```text
cross-run queue: executed=2 skipped=0
exit=0
```

## Assertions

- Both owning run-local jobs reached `succeeded`.
- Both cross-run queue entries reached `succeeded`.
- Queue claim locks were released.
- Both owning `state.json` files were byte-identical before and after queue execution.
