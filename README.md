# AI Coding Harness

这是一个 Codex-first 多 Agent 编排脚手架。目标是把 AI coding 工作拆成可分流、可验证、可审计、可接续的流程：Codex 负责主编排，Harness 负责规则、状态、证据和记忆，外部 Agent 只返回证据。

## 核心定位

- `Codex` 是主编排器，负责选择工作流、执行任务、更新当前 run 状态。
- `Harness` 是规则层，定义工作流、状态机、风险分级、验证、交接和长期记忆。
- `Claude Code` 在 v0.1 中只作为只读 reviewer，通过 MCP 工具 `claude_review` 返回审查证据。
- 外部 Agent 不能直接修改 Harness state，也不能替 Codex 做完成判定。

## 当前能力

- Fast / Standard / Strict 三类任务分流规则。
- 运行状态 schema：`harness/schemas/state.schema.json`。
- 可复制模板：task、plan、agent brief、agent result、verification、handoff。
- 示例 Fast 文档 run：`harness/runs/example-fast-doc-change/`。
- Codex 项目配置和自定义 agent：`.codex/`。
- Claude review MCP adapter：`mcp/claude-review/`。
- Python 单元测试覆盖 state schema 和 Claude review adapter 的关键安全路径。

## 目录结构

```text
AGENTS.md                         # Codex 入口规则和读取顺序
harness/core/                     # Agent-neutral Harness 核心规则
harness/adapters/                 # Codex、Claude Code、通用 CLI Agent 适配规则
harness/templates/                # 可复制任务和证据模板
harness/schemas/                  # 机器可校验 schema
harness/memory/                   # 长期记忆
harness/runs/                     # 每次任务的 run 记录和证据
.codex/                           # Codex 项目配置和自定义 agents
mcp/claude-review/                # Claude Code review MCP adapter
tests/                            # 单元测试
```

## 快速开始

先阅读入口规则：

```powershell
Get-Content AGENTS.md
```

运行测试：

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
python -m unittest discover -s tests -v
```

运行 Claude review adapter 的本地依赖安装：

```powershell
python -m pip install -r mcp/claude-review/requirements.lock.txt
```

启动 MCP server：

```powershell
python mcp/claude-review/server.py
```

## Claude Review Adapter 约束

`claude_review` 是同步 MCP 工具。它必须：

- 在调用 Claude 前检查输入预算和输出路径边界。
- 只把 `output_file`、`review_file`、`raw_log_file` 写入 `artifact_dir` 内。
- 对超预算、缺少工具、认证缺失、超时、schema invalid 等情况返回终态。
- 不允许 Claude Code 修改文件或 Harness state。

测试不会调用真实 Claude 模型；真实 CLI/auth 行为应在集成验证阶段单独确认。

## 工作流原则

- 没有验证证据，不声明完成。
- `timeout` 和 `not_available` 不是通过证据。
- 高风险任务必须升级到 Strict，并确认 scope、non-goals、恢复策略、验证计划和残余风险。
- 历史 run 记录默认 append-only，除非用户明确要求修正。

## 当前状态

v0.1 scaffold 已包含规则、schema、模板、Codex 配置、Claude review adapter 和单元测试。下一步可以围绕真实项目接入、实际 Claude CLI 集成验证、更多 Agent adapter 或 run 管理 CLI 继续演进。
