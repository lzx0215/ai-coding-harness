# Task

## Goal

Record implementation evidence and external review for the v0.2 reviewer provenance implementation.

## Track

Standard

## Workflow

standard-agent-adapter-change

## Scope

- Capture the Task 1-5 implementation diff from `master` to the current branch.
- Run final verification for tests, historical run validation, package health, and MCP server import.
- Run a real Claude review through the adapter.
- Record review provenance fields from the real review output.
- Complete the implementation run only after verification and review handling are recorded.

## Non-goals

- Add new provenance behavior beyond the committed v0.2 contract.
- Change auth, permissions, secrets, production configuration, or Claude Code permissions.
- Merge this branch to `master`.
- Rewrite completed historical run records.

## Acceptance Criteria

- The implementation run validates with `harness_version` and `state_schema_version` set to `0.2.0`.
- Diff artifacts cover the implementation commits, not only evidence files.
- Final verification evidence records tests, historical run validation, `pip check`, and MCP server import.
- Real Claude review output is captured and its reviewer provenance fields are inspected.
- Review disposition is recorded before the run reaches `completed`.
