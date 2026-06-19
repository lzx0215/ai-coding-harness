# Review

## Feedback Disposition

The sanity-check feedback identified a real plan bug: the planned `build_reviewer_provenance` code prioritized `modelUsage` over explicit `model` metadata. That would conflict with the existing `_reviewer_model` behavior and break `test_normalize_prefers_explicit_model_metadata_over_model_usage`.

## Changes Required

- Make explicit metadata set `primary_model` when present.
- Add the explicit metadata model as the first provenance model with source `metadata`.
- Preserve additional `modelUsage` entries after the metadata model.
- Skip duplicate `modelUsage` entry when it has the same name as the explicit metadata model.
- Add a focused test snippet for the combined explicit metadata plus `modelUsage` case.
- Include the existing scalar fallback regression in the Task 4 command.
- Expand the real review input-file generation instructions.

## Non-Blocking Notes

- The strict `parse_cli_version` behavior is acceptable because parsed `cli.version` is not used for gating in this slice.
- The implementation run must still prove the planned behavior with actual code and tests.

## Result

Plan amendment accepted for implementation planning.
