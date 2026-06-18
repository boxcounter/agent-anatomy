# Claude Code Agent Team 会话分析工具 —— 设计文档

## 背景与目标

研究 Claude Code Agent Team 的运行机制，重点分析 Sub-agent 模式和 Agent Team 模式的行为差异、协作逻辑和适用场景。

**核心问题**：
- Agent Team 是多进程的，不像单 session 可以用 claude-tap 直接分析
- Agent Team 模式运行时频繁修改通讯文件（mailbox、task），需捕获变更时序
- 两种模式（Sub-agent 同步 vs Agent Team 异步）的量化对比

**设计目标**：
- 调试 Agent 行为与协作逻辑
- 对比两种模式的延迟、Token 效率、协调开销、并行度
- 产出可复现、可迭代的分析框架

## 架构概览

```
                      ┌──────────────────┐
  Sub-agent 模式      │  collect         │  事后采集
  ──────────────      │  --session-id=X  │  直接读 JSONL
                      └──────────────────┘

                      ┌──────────────────┐
  Agent Team 模式     │  watch            │  运行时后台进程
  ──────────────      │  (kqueue 监控)    │  监控 mailbox/task
                      └──────────────────┘
                              │
                              ▼
                      ┌──────────────────┐
                      │  analyze          │  统一分析入口
                      │  --session-dir=X  │
                      └──────────────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
        events.jsonl   graph.mermaid    report.md
        timeline.html  state-machine
```

**采集与分析分离**：采集器只做原始数据规整，分析器做解析和关联。原始数据可复用，分析逻辑可独立迭代。

**为什么用 kqueue 而非 eslogger**：Agent Team 的写入是文件锁串行化的（proper-lockfile + flock），写入间隔远大于 kqueue 的合并窗口。kqueue 无需 sudo、无需系统权限，方案更干净。作为防御，每 5 秒兜底轮询一次做 diff 校验。

## 数据源与可靠性

| 数据源 | 格式 | 可靠性 | 说明 |
|--------|------|--------|------|
| 主 session JSONL | append-only | ✅ 完整 | 每条消息追加一行 |
| Sub-agent sidechain JSONL | append-only | ✅ 完整 | `isSidechain: true`, `parentUuid` 链接父消息 |
| Sub-agent meta.json | 固定 | ✅ 完整 | `agentType`, `toolUseId` 用于关联 |
| Team config.json | 覆写 | ⚠️ 最终态 | 成员列表、backend 类型 |
| Mailbox inboxes/*.json | 覆写（锁保护） | ⚠️ 最终态 + 时序 | `read` 标记变更通过 kqueue 捕获 |
| Task *.json | 覆写 | ⚠️ 最终态 | 状态转换通过 kqueue 捕获 |
| Session *.json | 覆写 | ⚠️ 瞬时态 | 进程生命周期信息 |

**权威数据源**：JSONL transcript。所有 tool call（SendMessage、TaskUpdate、Agent spawn）都在 transcript 中记录。Mailbox 和 task 文件只是实现机制，transcript 才是行为记录。

## 数据采集器

### `collect` —— Sub-agent 模式

事后运行，不需在 session 期间启动任何进程。

**输入**：session ID（从 `~/.claude/sessions/*.json` 中 `sessionId` 字段获取，或从 `~/.claude/projects/{sanitized-cwd}/` 目录名获取）

**执行逻辑**：
1. 定位 session 目录：`~/.claude/projects/*/{session-id}/`
2. 拷贝主 transcript → `analysis/raw/session.jsonl`
3. 遍历 `subagents/` 目录，拷贝所有 `agent-{id}.jsonl` + `agent-{id}.meta.json`
4. 提取 task 文件（如存在）：`~/.claude/tasks/{session-id}/*.json`
5. 提取 team config（如存在）：`~/.claude/teams/{session-id}/config.json`
6. 提取 mailbox 最终态（如存在）：`~/.claude/teams/{session-id}/inboxes/*.json`

**调用时机**：session 结束后。或在 session 运行期间调用以获取当前快照（JSONL 是 append-only，中途采集不会丢数据）。

### `watch` —— Agent Team 模式

运行时后台进程。在启动 Agent Team session **之前**启动，session 结束后停止。

**输入**：team name

**监控目标**：
- `~/.claude/teams/{team}/inboxes/` —— 所有 agent 的 mailbox
- `~/.claude/tasks/{team}/` —— 任务文件

**kqueue 实现要点**：
- 同时监控目录本身（`NOTE_WRITE`，感知文件增删）和每个已知文件（`NOTE_WRITE | NOTE_EXTEND`，感知内容变更）
- 目录变更时重新扫描文件列表，对新文件注册 kqueue
- 每次 `kevent()` 返回时，读取被变更文件的内容，写入 append-only 的 `team-events.jsonl`

**防御丢失**：每 5 秒无条件扫描一次目录内容，与上次快照做 diff。发现差异但未收到 kqueue 事件时，记录 `kind: "poll_catchup"` 事件并标记。

**输出格式**（`team-events.jsonl`，append-only）：
```json
{"timestamp": "2026-06-18T15:30:01.123Z", "path": ".../inboxes/agent-Y.json", "kind": "mailbox_snapshot", "content": [...]}
{"timestamp": "2026-06-18T15:30:02.456Z", "path": ".../tasks/1.json", "kind": "task_snapshot", "content": {...}}
```

## 解析层：统一事件流

所有来源的数据转换成同一种事件格式，按时间排序。分析层只消费这个统一流。

### 事件类型定义

```
UnifiedEvent:
  event_id: uuid
  timestamp: ISO 8601
  agent_id: str
  source: transcript | team_events
  type: agent_spawn | agent_complete | message_send | message_read |
        task_create | task_update | agent_message
  parent_id: uuid?         # 因果链
  data: object             # type 相关的 payload
```

| type | 来源 | 含义 | data 关键字段 |
|------|------|------|---------------|
| `agent_spawn` | Agent tool call（父 JSONL） | 派发 agent | `child_agent_id`, `agent_type`, `tool_use_id` |
| `agent_complete` | sidechain 结束 或 team-events | agent 结束 | `tokens_used`, `duration_ms`, `exit_reason` |
| `message_send` | SendMessage tool call | 发送消息 | `from`, `to`, `summary`, `message_type` |
| `message_read` | team-events diff | 消息被标记已读 | `mailbox_owner`, `from_agent`, 读取时间 |
| `task_create` | TaskCreate tool call | 创建任务 | `task_id`, `subject` |
| `task_update` | TaskUpdate tool call | 状态变更 | `task_id`, `new_status`, `old_status`, `owner` |
| `agent_message` | JSONL（主 + sidechain） | agent 的一次对话消息 | `role`, `content_summary`, `token_usage`, `tool_calls` |

### 关联逻辑

**Sub-agent 模式**：
```
主 JSONL 中 Agent tool call → tool_use_id
    → subagents/agent-X.meta.json 中 toolUseId 匹配
    → agent-X.jsonl 中 parentUuid 指向父消息
```

**Agent Team 模式**：
```
team-events.jsonl 中 mailbox 快照
    → 比较前后快照 diff
    → message_send 事件：新增消息条目
    → message_read 事件：read 标记 false → true
    → 按时间戳与 JSONL 中的 SendMessage tool call 对齐
```

**输出**：单个 `events.jsonl` 文件，所有事件按 `timestamp` 升序，不区分来源。

## 分析层

### 时间线

分层时间线——每个 agent 一行，事件按行对齐：

```
主 session  │── spawn(a0) ──┬────────────── recv result ──│
            │              │
agent-a0   │              └── msg1 ── msg2 ── done ──│
agent-a1   │                         ─── spawn(a1) ── msg3 ── done ──│
            │
            ├──────────────┼──────────────┼──────────────┤
          t=0             t=30s          t=60s         t=90s
```

- 点：事件时间位置
- 连线：`parent_id` 关联的因果箭头（如 spawn 链）
- 颜色区分事件 type
- 悬停显示 data payload 摘要
- D3.js 生成静态 HTML（无需后端）

### 协作图

有向图，节点 = agent，边 = `message_send` 事件（from → to），标注消息数量和类型。输出 Mermaid 格式。

**额外分析**：
- 通讯密度：每个 agent 与多少个其他 agent 交互
- 信息流向：中心辐射 vs 点对点
- 消息延迟：`message_send` → `message_read` 的时间差（仅 Agent Team 模式）

### 任务状态机

从 `task_create` 和 `task_update` 事件重建每个 task 的状态转换：

```
task-1:
  pending ──(a0, t=5s)──▶ in_progress ──(a0, t=45s)──▶ completed
```

**异常检测**：
- 任务在 `in_progress` 状态下没有后续事件
- 任务没有 `task_create` 却有 `task_update`
- `blockedBy` 指向的任务不存在

### 对比分析

对同一场景（相同的 prompt 和初始上下文，分别用 Sub-agent 和 Agent Team 模式执行）分别跑两次，产出对比：

| 维度 | 指标 |
|------|------|
| 延迟 | 问题提出 → 最终答案的总耗时 |
| Token 效率 | 总 token / 有用产出（按 agent 维度拆分） |
| 协调开销 | 通讯消息数、等待时间 |
| 并行度 | agent 重叠运行时间段 |
| 容错 | 任务重试、超时、shutdown 拒绝 |

## 输出文件结构

```
~/.claude/projects/{sanitized-cwd}/{session-id}/analysis/
├── raw/
│   ├── session.jsonl            # 主 transcript 副本
│   ├── subagents/               # sidechain 副本
│   │   ├── agent-{id}.jsonl
│   │   └── agent-{id}.meta.json
│   └── team-events.jsonl        # watch 产物（仅 Agent Team 模式）
├── events.jsonl                 # 统一事件流
├── timeline.html                # 交互式时间线
├── graph.mermaid                # 协作图
└── report.md                    # 对比分析报告
```

## 实现方案

### 技术选型

| 维度 | 选择 |
|------|------|
| 语言 | Python 3.12+ |
| 包管理 | uv |
| CLI 框架 | click |
| 模板引擎 | Jinja2 |
| 类型检查 | Pyright（strict mode） |
| Lint/Format | ruff |
| 测试 | pytest |
| kqueue | `select.kqueue()` 标准库 |

### Python 编码规范

- Type hints：Python 3.10+ 语法（`str | None`，非 `Optional[str]`；`list[str]`，非 `List[str]`）
- 所有公开函数必须有完整 type annotations
- `pyproject.toml` 集中配置所有工具
- `src` layout

### 命令结构

```
analysis-tool
├── collect   --session-id=<id>          # 事后采集（Sub-agent 模式）
├── watch     --team-name=<name>         # 运行时监控（Agent Team 模式）
└── analyze   --session-dir=<dir>        # 分析 + 生成报告
       └── --output=<dir>                # 默认 analysis/
```

### 目录结构

```
agent-team-research/
├── pyproject.toml
├── src/
│   └── analysis_tool/
│       ├── __init__.py
│       ├── cli.py              # 入口，click 命令分发
│       ├── collect.py          # collect 逻辑
│       ├── watch.py            # kqueue 监控
│       ├── parser.py           # JSONL / meta / team-events → 统一事件流
│       ├── timeline.py         # 时间线（D3.js HTML 模板）
│       ├── graph.py            # 协作图（Mermaid 生成）
│       ├── state_machine.py    # 任务状态机重建
│       ├── comparator.py       # 对比分析
│       └── templates/
│           └── timeline.html.j2
├── tests/
│   ├── fixtures/               # 测试用的 mock session 数据
│   ├── test_collect.py
│   ├── test_parser.py
│   ├── test_timeline.py
│   ├── test_graph.py
│   ├── test_state_machine.py
│   └── test_comparator.py
└── docs/
    └── superpowers/
        └── specs/
            └── 2026-06-18-agent-team-analysis-design.md
```

### 交付阶段

| 阶段 | 内容 |
|------|------|
| 1 | `collect` + `parser`（Sub-agent 模式完整链路） |
| 2 | `analyze`（时间线 + 协作图 + 状态机 + CLI 报告） |
| 3 | `watch`（Agent Team 模式 kqueue 监控） |
| 4 | `comparator`（两种模式对比报告） |
| 5 | HTML 时间线 + Mermaid 图渲染 |

阶段 1 是最小可用里程碑——跑通 Sub-agent 模式的数据采集→解析→分析。后续阶段都是增量增强。
