# Agent Anatomy

[![CI](https://github.com/boxcounter/agent-anatomy/actions/workflows/ci.yml/badge.svg)](https://github.com/boxcounter/agent-anatomy/actions/workflows/ci.yml)

剖析 Claude Code 多 agent 会话的工具，支持 sub-agent、agent team、workflow 三种协作模式。采集 session 的原始数据，产出统一事件流、交互式时间线、协作图，以及揭示协作机制的分析报告。

## 安装

```bash
# 需要 Python 3.12+
uv sync
```

## 命令

### `collect` —— 事后采集 Sub-agent / Workflow 模式 session

Session 结束后运行。拷贝 JSONL transcript、sub-agent sidechain，以及 Workflow 运行日志（`workflows/wf_*.json`，Workflow 模式的权威拓扑）到统一目录。

```bash
uv run anatomy collect --session-id=<session-id>

# 查找 session ID
ls ~/.claude/projects/*/
```

### `watch` —— 运行时监控 Agent Team 模式

在启动 Agent Team session **之前**启动，Ctrl+C 停止。通过 kqueue 监控 mailbox 和 task 文件变更。

```bash
uv run anatomy watch --team-name=<team-name>
```

### `analyze` —— 生成分析报告

从采集/监控的原始数据中生成分析产物。

```bash
uv run anatomy analyze --session-dir=<path-to-analysis-dir>
```

产出：
- `report.html` —— 单文件 explainer（旗舰）：模式讲解 + 协作图 + 时间线 + 每个 agent 可点开的完整输出
- `report.md` —— 同内容的 Markdown 版分析报告
- `timeline.html` —— D3.js 交互式时间线
- `graph.mermaid` —— 协作图（Mermaid 格式）
- `events.jsonl` —— 统一事件流
- `agents/` —— 每个 agent 一个 Markdown 文件，完整未截断输出

## 开发

```bash
uv sync --extra dev            # 安装开发依赖（pytest / ruff / pyright）
uv run pytest tests/ -v        # 运行测试
uv run ruff check src/ tests/  # Lint
uv run pyright src/ tests/     # 类型检查
```

### 技术选型

Python 3.12+, uv, Click, Jinja2, D3.js, pytest, ruff, pyright (strict mode)。
