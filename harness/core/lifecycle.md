# Lifecycle

## Lifecycle

`Discover -> Define -> Deliver -> Verify -> Review -> Handoff -> Improve`

## Workflow Registry

| Workflow ID | Track | Applies to | Required stages |
| --- | --- | --- | --- |
| `fast-doc-change` | Fast | Copy, typo, or formatting-only documentation changes. | Discover, Deliver, Verify, Handoff summary. |
| `fast-code-change` | Fast | Very small low-risk code edits with obvious local validation. | Discover, Deliver, Verify, Handoff summary. |
| `standard-doc-system-change` | Standard | Documentation structure, templates, process rules, or harness documents. | Discover, Define, Deliver, Verify, Review optional, Handoff, Improve optional. |
| `standard-code-change` | Standard | Normal code changes, features, bug fixes, refactors, or test changes. | Discover, Define, Deliver, Verify, Review, Handoff, Improve optional. |
| `standard-agent-adapter-change` | Standard | MCP adapter, agent wrapper, schema, or non-destructive integration changes. | Discover, Define, Deliver, Verify, Review, Handoff, Improve optional. |
| `strict-risk-change` | Strict | Auth, security, permissions, secrets, production config, database, payments, or privacy-sensitive changes. | Discover, Define with user confirmation, Deliver, Verify, Review, Handoff, Improve. |
| `strict-destructive-change` | Strict | Deletion, irreversible migration, broad cleanup, or state/history rewriting. | Discover, Define with scope and recovery confirmation, Deliver, Verify, Review, Handoff, Improve. |

## Rule

Codex must not invent a workflow ID. Add new workflow IDs here before using them.
