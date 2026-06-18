# Agent Team 会话分析工具 —— 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个 CLI 工具，采集 Claude Code session 的原始数据并产出统一事件流、协作图、任务状态机和对比分析报告。

**Architecture:** 采集与分析分离。`collect` 命令事后拷贝原始 JSONL/meta 文件；`watch` 命令通过 kqueue 运行时监控 Agent Team 的 mailbox/task 文件变更。两者产出统一格式的原始数据，`analyze` 命令解析为统一事件流并生成分析产物。

**Tech Stack:** Python 3.12+, uv, click, Jinja2, pytest, ruff, Pyright (strict mode), select.kqueue 标准库

---

## 文件结构

```
agent-team-research/
├── pyproject.toml                    # 项目配置（依赖、ruff、pyright、pytest）
├── src/
│   └── analysis_tool/
│       ├── __init__.py
│       ├── models.py                 # 所有 dataclass / enum 类型定义
│       ├── cli.py                    # Click 命令入口
│       ├── collect.py                # collect 命令实现
│       ├── watch.py                  # watch 命令实现（kqueue）
│       ├── parser.py                 # JSONL/meta/team-events → 统一事件流
│       ├── state_machine.py          # 任务状态机重建 + 异常检测
│       ├── graph.py                  # 协作图（Mermaid 生成）
│       ├── comparator.py             # 两种模式对比分析
│       ├── timeline.py               # 时间线数据 + HTML 生成
│       └── templates/
│           └── timeline.html.j2       # D3.js 时间线模板
├── tests/
│   ├── fixtures/
│   │   ├── session.jsonl             # mock 主 session（至少含 1 个 Agent tool call）
│   │   ├── subagents/
│   │   │   ├── agent-a0.jsonl        # mock sidechain
│   │   │   └── agent-a0.meta.json    # mock meta
│   │   ├── team-config.json          # mock team config
│   │   ├── inboxes/
│   │   │   └── agent-x.json          # mock mailbox 最终态
│   │   └── team-events.jsonl         # mock team-events（含前后两个快照）
│   ├── conftest.py
│   ├── test_models.py
│   ├── test_collect.py
│   ├── test_parser.py
│   ├── test_state_machine.py
│   ├── test_graph.py
│   ├── test_comparator.py
│   └── test_timeline.py
└── docs/
    └── superpowers/
        ├── specs/
        │   └── 2026-06-18-agent-team-analysis-design.md
        └── plans/
            └── 2026-06-18-agent-team-analysis-plan.md
```

### 各模块接口

**`models.py`** — 纯类型定义，无逻辑。被所有模块 import。

**`collect.py`** — `collect_session(session_id: str, output_dir: Path) -> Path`。返回 `analysis/raw/` 目录路径。所有文件路径操作通过 `pathlib.Path`。

**`watch.py`** — `watch_teams(team_name: str, output_dir: Path, stop_event: threading.Event) -> None`。阻塞运行直到 `stop_event` 被设置。产出 `team-events.jsonl`。

**`parser.py`** — `parse_raw_dir(raw_dir: Path) -> list[UnifiedEvent]`。读取 `raw/` 目录所有文件，返回按时间戳排序的事件列表。`parse_jsonl(path: Path) -> list[UnifiedEvent]` 解析单个 JSONL；`parse_team_events(path: Path) -> list[UnifiedEvent]` 解析 team-events 并做 diff。

**`state_machine.py`** — `build_state_machines(events: list[UnifiedEvent]) -> dict[str, list[StateTransition]]`。`detect_anomalies(machines: dict) -> list[Anomaly]`。

**`graph.py`** — `build_collaboration_graph(events: list[UnifiedEvent]) -> Graph`。`to_mermaid(graph: Graph) -> str`。

**`comparator.py`** — `compare(events_a: list[UnifiedEvent], mode_a: str, events_b: list[UnifiedEvent], mode_b: str) -> ComparisonReport`。`_session_summary(events: list[UnifiedEvent]) -> str`。

**`timeline.py`** — `build_timeline_data(events: list[UnifiedEvent]) -> dict`。产出 JSON 结构。`render_html(data: dict, template_path: Path, output_path: Path) -> None`。

**`cli.py`** — 三个 Click 命令：`collect`（调用 `collect_session`）、`watch`（创建线程调用 `watch_teams`，阻塞等待 SIGINT/SIGTERM）、`analyze`（调用 `parse_raw_dir` + 各分析模块 + 渲染输出）。命令间仅通过文件系统交换数据。

---

## Phase 1: 项目骨架 + collect + parser（Sub-agent 链路）

### Task 1: 项目初始化

**Files:**
- Create: `pyproject.toml`
- Create: `src/analysis_tool/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: 创建 pyproject.toml**

```toml
[project]
name = "analysis-tool"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "click>=8.1",
    "jinja2>=3.1",
]

[project.optional-dependencies]
dev = [
    "pytest>=8",
    "ruff>=0.11",
    "pyright>=1.1",
]

[project.scripts]
analysis-tool = "analysis_tool.cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.ruff]
target-version = "py312"
line-length = 120

[tool.ruff.lint]
select = ["E", "F", "I", "N", "W", "UP"]

[tool.ruff.format]
quote-style = "double"

[tool.pyright]
typeCheckingMode = "strict"
pythonVersion = "3.12"

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: 初始化 uv 项目**

```bash
cd /Users/boxcounter/Code/Boxcounter/agent-team-research
uv venv --python 3.12
source .venv/bin/activate
uv pip install -e ".[dev]"
```

或者直接用 uv sync:
```bash
uv sync
```

- [ ] **Step 3: 创建空的 `__init__.py` 和 `conftest.py`**

```python
# tests/conftest.py
from pathlib import Path

import pytest


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"
```

- [ ] **Step 4: 验证项目可导入**

```bash
uv run python -c "import analysis_tool; print('OK')"
```
Expected: `OK`

- [ ] **Step 5: 验证 ruff 和 pyright 通过（空项目）**

```bash
uv run ruff check src/ tests/
uv run pyright src/ tests/
```
Expected: both pass with no errors

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/analysis_tool/__init__.py tests/__init__.py tests/conftest.py
git commit -m "chore: initialize project with uv, ruff, pyright"
```

### Task 2: 类型模型

**Files:**
- Create: `src/analysis_tool/models.py`
- Create: `tests/test_models.py`

- [ ] **Step 1: 写 failing test（验证 UnifiedEvent 不可变且字段正确）**

```python
# tests/test_models.py
import uuid
from datetime import datetime, timezone

from analysis_tool.models import EventType, EventSource, UnifiedEvent


def test_unified_event_construction():
    event_id = uuid.uuid4()
    ts = datetime.now(timezone.utc)
    event = UnifiedEvent(
        event_id=event_id,
        timestamp=ts,
        agent_id="agent-1",
        source=EventSource.TRANSCRIPT,
        type=EventType.AGENT_MESSAGE,
        parent_id=None,
        data={"role": "assistant", "content_summary": "hello"},
    )
    assert event.event_id == event_id
    assert event.timestamp == ts
    assert event.agent_id == "agent-1"
    assert event.source == EventSource.TRANSCRIPT
    assert event.type == EventType.AGENT_MESSAGE
    assert event.parent_id is None
    assert event.data["role"] == "assistant"


def test_unified_event_is_frozen():
    event = UnifiedEvent(
        event_id=uuid.uuid4(),
        timestamp=datetime.now(timezone.utc),
        agent_id="a",
        source=EventSource.TRANSCRIPT,
        type=EventType.AGENT_MESSAGE,
        data={},
    )
    # dataclass with frozen=True should raise on attribute set
    try:
        event.agent_id = "b"
        assert False, "Should have raised FrozenInstanceError"
    except Exception:
        pass
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_models.py -v
```
Expected: FAIL (module not found, import error)

- [ ] **Step 3: 实现 models.py**

```python
# src/analysis_tool/models.py
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, auto
from typing import Any
from uuid import UUID, uuid4


class EventSource(Enum):
    TRANSCRIPT = "transcript"
    TEAM_EVENTS = "team_events"


class EventType(Enum):
    AGENT_SPAWN = "agent_spawn"
    AGENT_COMPLETE = "agent_complete"
    MESSAGE_SEND = "message_send"
    MESSAGE_READ = "message_read"
    TASK_CREATE = "task_create"
    TASK_UPDATE = "task_update"
    AGENT_MESSAGE = "agent_message"


@dataclass(frozen=True)
class UnifiedEvent:
    event_id: UUID
    timestamp: datetime
    agent_id: str
    source: EventSource
    type: EventType
    data: dict[str, Any]
    parent_id: UUID | None = None

    @classmethod
    def create(
        cls,
        *,
        timestamp: datetime,
        agent_id: str,
        source: EventSource,
        type: EventType,
        data: dict[str, Any],
        parent_id: UUID | None = None,
    ) -> "UnifiedEvent":
        return cls(
            event_id=uuid4(),
            timestamp=timestamp,
            agent_id=agent_id,
            source=source,
            type=type,
            data=data,
            parent_id=parent_id,
        )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_models.py -v
```
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/analysis_tool/models.py tests/test_models.py
git commit -m "feat: add UnifiedEvent type model"
```

### Task 3: JSONL Parser

**Files:**
- Create: `src/analysis_tool/parser.py`
- Create: `tests/test_parser.py`
- Create: `tests/fixtures/session.jsonl`
- Create: `tests/fixtures/subagents/agent-a0.meta.json`
- Create: `tests/fixtures/subagents/agent-a0.jsonl`

- [ ] **Step 1: 创建 mock 数据 — meta.json**

```json
{
  "agentType": "general-purpose",
  "toolUseId": "call_00_abc123",
  "description": "test agent"
}
```

保存到 `tests/fixtures/subagents/agent-a0.meta.json`

- [ ] **Step 2: 创建 mock 数据 — 主 session JSONL（含一个 Agent tool call）**

主 session 中简化的一条 assistant message，包含 Agent tool call：
```json
{"parentUuid":null,"isSidechain":false,"agentId":"main","message":{"role":"assistant","content":[{"type":"tool_use","id":"call_00_abc123","name":"Agent","input":{"description":"test task","prompt":"do something"}}]},"uuid":"m1","timestamp":"2026-06-18T12:00:00.000Z"}
```
保存到 `tests/fixtures/session.jsonl`

- [ ] **Step 3: 创建 mock 数据 — sub-agent sidechain JSONL**

```json
{"parentUuid":"m1","isSidechain":true,"agentId":"agent-a0","message":{"role":"assistant","content":[{"type":"text","text":"I am a sub-agent response"}]},"uuid":"s1","timestamp":"2026-06-18T12:00:30.000Z"}
```

保存到 `tests/fixtures/subagents/agent-a0.jsonl`

- [ ] **Step 4: 写 failing test — 解析主 JSONL 生成 agent_spawn 事件**

```python
# tests/test_parser.py
from pathlib import Path

from analysis_tool.models import EventType, EventSource
from analysis_tool.parser import parse_jsonl


def test_parse_session_jsonl_yields_agent_spawn(fixtures_dir: Path):
    events = parse_jsonl(fixtures_dir / "session.jsonl")
    spawns = [e for e in events if e.type == EventType.AGENT_SPAWN]
    assert len(spawns) == 1
    spawn = spawns[0]
    assert spawn.source == EventSource.TRANSCRIPT
    assert spawn.agent_id == "main"
    assert spawn.data["child_agent_id"] == ""
    assert spawn.data["tool_use_id"] == "call_00_abc123"
    assert spawn.data["agent_type"] == "general-purpose"


def test_parse_subagent_jsonl_yields_agent_message(fixtures_dir: Path):
    events = parse_jsonl(fixtures_dir / "subagents" / "agent-a0.jsonl")
    msgs = [e for e in events if e.type == EventType.AGENT_MESSAGE]
    assert len(msgs) == 1
    msg = msgs[0]
    assert msg.agent_id == "agent-a0"
    assert msg.source == EventSource.TRANSCRIPT
    assert msg.data["role"] == "assistant"
    assert msg.data["content_summary"] == "I am a sub-agent response"
    assert msg.parent_id is not None  # parentUuid mapped
```

- [ ] **Step 5: Run tests to verify they fail**

```bash
uv run pytest tests/test_parser.py -v
```
Expected: FAIL

- [ ] **Step 6: 实现 parse_jsonl**

```python
# src/analysis_tool/parser.py
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from analysis_tool.models import EventType, EventSource, UnifiedEvent


def parse_jsonl(path: Path) -> list[UnifiedEvent]:
    events: list[UnifiedEvent] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            parsed = _parse_jsonl_entry(entry)
            events.extend(parsed)
    return events


def _parse_jsonl_entry(entry: dict[str, Any]) -> list[UnifiedEvent]:
    events: list[UnifiedEvent] = []
    agent_id = entry.get("agentId", "unknown")
    ts = datetime.fromisoformat(entry["timestamp"].replace("Z", "+00:00"))
    parent_uuid_raw = entry.get("parentUuid")
    parent_id = uuid.UUID(parent_uuid_raw) if parent_uuid_raw else None

    message = entry.get("message", {})
    content = message.get("content", [])

    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                name = block.get("name", "")
                tool_input = block.get("input", {})
                tool_id = block.get("id", "")

                if name == "Agent":
                    events.append(UnifiedEvent.create(
                        timestamp=ts,
                        agent_id=agent_id,
                        source=EventSource.TRANSCRIPT,
                        type=EventType.AGENT_SPAWN,
                        data={
                            "child_agent_id": "",
                            "tool_use_id": tool_id,
                            "agent_type": tool_input.get("subagent_type", ""),
                            "description": tool_input.get("description", ""),
                        },
                        parent_id=parent_id,
                    ))
                elif name == "SendMessage":
                    events.append(UnifiedEvent.create(
                        timestamp=ts,
                        agent_id=agent_id,
                        source=EventSource.TRANSCRIPT,
                        type=EventType.MESSAGE_SEND,
                        data={
                            "from": agent_id,
                            "to": tool_input.get("to", ""),
                            "summary": tool_input.get("summary", ""),
                            "message_type": tool_input.get("message", {}).get("type", "message")
                            if isinstance(tool_input.get("message"), dict)
                            else "message",
                        },
                        parent_id=parent_id,
                    ))
                elif name == "TaskCreate":
                    events.append(UnifiedEvent.create(
                        timestamp=ts,
                        agent_id=agent_id,
                        source=EventSource.TRANSCRIPT,
                        type=EventType.TASK_CREATE,
                        data={
                            "task_id": "",
                            "subject": tool_input.get("subject", ""),
                            "description": tool_input.get("description", ""),
                        },
                        parent_id=parent_id,
                    ))
                elif name == "TaskUpdate":
                    events.append(UnifiedEvent.create(
                        timestamp=ts,
                        agent_id=agent_id,
                        source=EventSource.TRANSCRIPT,
                        type=EventType.TASK_UPDATE,
                        data={
                            "task_id": tool_input.get("taskId", ""),
                            "new_status": tool_input.get("status", ""),
                            "old_status": "",
                            "owner": tool_input.get("owner", ""),
                        },
                        parent_id=parent_id,
                    ))

    # Also emit an agent_message event for the text content
    text_parts = [
        b.get("text", "")
        for b in (content if isinstance(content, list) else [])
        if isinstance(b, dict) and b.get("type") == "text"
    ]
    if text_parts:
        summary = " ".join(text_parts)[:200]  # truncated summary
    else:
        summary = ""

    if summary:
        events.append(UnifiedEvent.create(
            timestamp=ts,
            agent_id=agent_id,
            source=EventSource.TRANSCRIPT,
            type=EventType.AGENT_MESSAGE,
            data={
                "role": message.get("role", "unknown"),
                "content_summary": summary,
                "token_usage": message.get("usage", {}),
                "tool_calls": [
                    b.get("name")
                    for b in (content if isinstance(content, list) else [])
                    if isinstance(b, dict) and b.get("type") == "tool_use"
                ],
            },
            parent_id=parent_id,
        ))

    return events
```

- [ ] **Step 7: Run tests to verify they pass**

```bash
uv run pytest tests/test_parser.py -v
```
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add src/analysis_tool/parser.py tests/test_parser.py tests/fixtures/
git commit -m "feat: add JSONL parser with Agent/SendMessage/Task tool call extraction"
```

### Task 4: Sidechain 关联（meta.json 匹配 child_agent_id）

**Files:**
- Modify: `src/analysis_tool/parser.py`
- Modify: `tests/test_parser.py`

- [ ] **Step 1: 写 failing test — parse_raw_dir 关联 spawn 和 sidechain**

```python
# 追加到 tests/test_parser.py
from analysis_tool.parser import parse_raw_dir


def test_parse_raw_dir_links_spawn_to_sidechain(fixtures_dir: Path):
    events = parse_raw_dir(fixtures_dir)

    spawns = [e for e in events if e.type == EventType.AGENT_SPAWN]
    assert len(spawns) == 1
    spawn = spawns[0]
    # After association, child_agent_id should be populated
    assert spawn.data["child_agent_id"] != ""
    assert "agent-a0" in spawn.data["child_agent_id"]

    # Verify sidechain messages exist and reference the spawn
    sidechain_msgs = [
        e for e in events
        if e.type == EventType.AGENT_MESSAGE and e.agent_id == "agent-a0"
    ]
    assert len(sidechain_msgs) >= 1
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_parser.py::test_parse_raw_dir_links_spawn_to_sidechain -v
```
Expected: FAIL

- [ ] **Step 3: 实现 parse_raw_dir（含 sidechain 关联）**

```python
# 追加到 src/analysis_tool/parser.py

def parse_raw_dir(raw_dir: Path) -> list[UnifiedEvent]:
    """Parse all raw data in a session analysis/raw directory into unified events."""
    all_events: list[UnifiedEvent] = []

    # 1. Parse main session transcript
    session_jsonl = raw_dir / "session.jsonl"
    if session_jsonl.exists():
        all_events.extend(parse_jsonl(session_jsonl))

    # 2. Parse subagent sidechains
    subagents_dir = raw_dir / "subagents"
    if subagents_dir.is_dir():
        for meta_file in sorted(subagents_dir.glob("*.meta.json")):
            meta = json.loads(meta_file.read_text())
            tool_use_id = meta.get("toolUseId", "")
            # meta file: "agent-a0.meta.json" -> agent_id: "agent-a0"
            sidechain_stem = meta_file.name.replace(".meta.json", "")
            agent_id = sidechain_stem

            # Match against existing agent_spawn events and update child_agent_id
            for event in all_events:
                if (
                    event.type == EventType.AGENT_SPAWN
                    and event.data.get("tool_use_id") == tool_use_id
                ):
                    idx = all_events.index(event)
                    all_events[idx] = UnifiedEvent.create(
                        timestamp=event.timestamp,
                        agent_id=event.agent_id,
                        source=event.source,
                        type=event.type,
                        data={**event.data, "child_agent_id": agent_id},
                        parent_id=event.parent_id,
                    )

            # Parse the sidechain JSONL
            sidechain_jsonl = subagents_dir / f"{sidechain_stem}.jsonl"
            if sidechain_jsonl.exists():
                sidechain_events = parse_jsonl(sidechain_jsonl)
                all_events.extend(sidechain_events)

    # 3. Parse team-events if present
    team_events_file = raw_dir / "team-events.jsonl"
    if team_events_file.exists():
        all_events.extend(parse_team_events(team_events_file))

    # Sort by timestamp
    all_events.sort(key=lambda e: e.timestamp)

    return all_events


def parse_team_events(path: Path) -> list[UnifiedEvent]:
    """Parse team-events.jsonl and diff consecutive snapshots to find message_read events."""
    events: list[UnifiedEvent] = []
    snapshots: list[dict[str, Any]] = []

    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            snapshots.append(json.loads(line))

    for i, snap in enumerate(snapshots):
        ts = datetime.fromisoformat(snap["timestamp"].replace("Z", "+00:00"))

        # On first snapshot, just record baseline
        if i == 0 and snap.get("kind") == "mailbox_snapshot":
            content = snap.get("content", [])
            if isinstance(content, list):
                for msg in content:
                    if isinstance(msg, dict):
                        events.append(UnifiedEvent.create(
                            timestamp=ts,
                            agent_id=snap.get("path", ""),
                            source=EventSource.TEAM_EVENTS,
                            type=EventType.MESSAGE_SEND,
                            data={
                                "from": msg.get("from", ""),
                                "to": Path(snap["path"]).stem,
                                "summary": msg.get("summary", ""),
                                "message_type": "message",
                            },
                        ))

        # Diff with previous to find read transitions
        if i > 0:
            prev = snapshots[i - 1]
            if snap.get("kind") == "mailbox_snapshot" and prev.get("kind") == "mailbox_snapshot":
                prev_content = prev.get("content", [])
                curr_content = snap.get("content", [])
                if isinstance(prev_content, list) and isinstance(curr_content, list):
                    _diff_mailbox(prev_content, curr_content, ts, snap["path"], events)

    return events


def _diff_mailbox(
    prev_content: list[dict[str, Any]],
    curr_content: list[dict[str, Any]],
    ts: datetime,
    path: str,
    events: list[UnifiedEvent],
) -> None:
    """Compare mailbox snapshots to detect new messages and read transitions."""
    mailbox_owner = Path(path).stem

    # Detect new messages (present in curr but not in prev)
    if len(curr_content) > len(prev_content):
        for msg in curr_content[len(prev_content):]:
            if isinstance(msg, dict):
                events.append(UnifiedEvent.create(
                    timestamp=ts,
                    agent_id=mailbox_owner,
                    source=EventSource.TEAM_EVENTS,
                    type=EventType.MESSAGE_SEND,
                    data={
                        "from": msg.get("from", ""),
                        "to": mailbox_owner,
                        "summary": msg.get("summary", ""),
                        "message_type": "message",
                    },
                ))

    # Detect read transitions (read: false -> true)
    for prev_msg, curr_msg in zip(prev_content, curr_content):
        if (
            isinstance(prev_msg, dict) and isinstance(curr_msg, dict)
            and not prev_msg.get("read", False)
            and curr_msg.get("read", False)
        ):
            events.append(UnifiedEvent.create(
                timestamp=ts,
                agent_id=mailbox_owner,
                source=EventSource.TEAM_EVENTS,
                type=EventType.MESSAGE_READ,
                data={
                    "mailbox_owner": mailbox_owner,
                    "from_agent": curr_msg.get("from", ""),
                    "summary": curr_msg.get("summary", ""),
                },
            ))
```

- [ ] **Step 4: 验证 test_parse_raw_dir 通过**

```bash
uv run pytest tests/test_parser.py::test_parse_raw_dir_links_spawn_to_sidechain -v
```
Expected: PASS

- [ ] **Step 5: Verify all parser tests pass**

```bash
uv run pytest tests/test_parser.py -v
```
Expected: all PASS

- [ ] **Step 6: Run ruff + pyright**

```bash
uv run ruff check src/analysis_tool/parser.py
uv run pyright src/analysis_tool/parser.py
```
Expected: both pass

- [ ] **Step 7: Commit**

```bash
git add src/analysis_tool/parser.py tests/test_parser.py
git commit -m "feat: add parse_raw_dir with sidechain association and team-events diff"
```

### Task 5: collect 命令

**Files:**
- Create: `src/analysis_tool/collect.py`
- Create: `tests/test_collect.py`

- [ ] **Step 1: 写 failing test — collect_session 拷贝文件**

```python
# tests/test_collect.py
from pathlib import Path

from analysis_tool.collect import collect_session


def test_collect_session_copies_session_jsonl(tmp_path: Path, monkeypatch):
    """collect_session copies the main session JSONL into raw/."""
    # Mock ~/.claude/projects path
    fake_projects = tmp_path / "projects"
    fake_projects.mkdir()
    session_dir = fake_projects / "test-project" / "sid-1234"
    session_dir.mkdir(parents=True)
    (session_dir / "sid-1234.jsonl").write_text('{"test": true}\n')

    subagents_dir = session_dir / "sid-1234" / "subagents"
    subagents_dir.mkdir(parents=True)
    (subagents_dir / "agent-x.jsonl").write_text('{"sidechain": true}\n')
    (subagents_dir / "agent-x.meta.json").write_text('{"toolUseId": "call_123"}')

    output_dir = tmp_path / "analysis"

    # Replace home expansion
    monkeypatch.setattr(
        "analysis_tool.collect._find_session_dir",
        lambda session_id: session_dir,
    )

    result = collect_session("sid-1234", output_dir)

    assert (result / "raw" / "session.jsonl").exists()
    assert (result / "raw" / "subagents" / "agent-x.jsonl").exists()
    assert (result / "raw" / "subagents" / "agent-x.meta.json").exists()
    content = (result / "raw" / "session.jsonl").read_text()
    assert "test" in content
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_collect.py -v
```
Expected: FAIL

- [ ] **Step 3: 实现 collect.py**

```python
# src/analysis_tool/collect.py
import json
import shutil
from pathlib import Path


def _find_session_dir(session_id: str) -> Path:
    """Search ~/.claude/projects/ for a session directory."""
    claude_projects = Path.home() / ".claude" / "projects"
    for project_dir in claude_projects.iterdir():
        if not project_dir.is_dir():
            continue
        session_dir = project_dir / session_id
        if session_dir.is_dir():
            return session_dir
    raise FileNotFoundError(f"Session directory not found for {session_id}")


def collect_session(session_id: str, output_dir: Path) -> Path:
    """Collect all raw data for a session into output_dir/raw/.

    Returns the analysis directory path.
    """
    analysis_dir = output_dir / "analysis"
    raw_dir = analysis_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    session_dir = _find_session_dir(session_id)

    # 1. Copy main transcript
    jsonl_file = session_dir / f"{session_id}.jsonl"
    if jsonl_file.exists():
        shutil.copy2(jsonl_file, raw_dir / "session.jsonl")

    # 2. Copy subagent sidechains
    subagents_src = session_dir / session_id / "subagents"
    subagents_dst = raw_dir / "subagents"
    if subagents_src.is_dir():
        subagents_dst.mkdir(exist_ok=True)
        for f in subagents_src.iterdir():
            shutil.copy2(f, subagents_dst / f.name)

    # 3. Copy task files (if session used tasks)
    tasks_dir = Path.home() / ".claude" / "tasks" / session_id
    if tasks_dir.is_dir():
        tasks_dst = raw_dir / "tasks"
        tasks_dst.mkdir(exist_ok=True)
        for f in tasks_dir.iterdir():
            if f.suffix == ".json":
                shutil.copy2(f, tasks_dst / f.name)

    # 4. Copy team config and inboxes
    teams_dir = Path.home() / ".claude" / "teams" / session_id
    if teams_dir.is_dir():
        config_file = teams_dir / "config.json"
        if config_file.exists():
            shutil.copy2(config_file, raw_dir / "team-config.json")

        inboxes_src = teams_dir / "inboxes"
        inboxes_dst = raw_dir / "inboxes"
        if inboxes_src.is_dir():
            inboxes_dst.mkdir(exist_ok=True)
            for f in inboxes_src.iterdir():
                shutil.copy2(f, inboxes_dst / f.name)

    return analysis_dir
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_collect.py -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/analysis_tool/collect.py tests/test_collect.py
git commit -m "feat: add collect_session for Sub-agent mode data gathering"
```

### Task 6: CLI 入口（collect 命令）

**Files:**
- Create: `src/analysis_tool/cli.py`

- [ ] **Step 1: 写 CLI 入口（手动验证，暂不写自动化测试）**

```python
# src/analysis_tool/cli.py
import click

from analysis_tool.collect import collect_session
from analysis_tool.parser import parse_raw_dir


@click.group()
def main() -> None:
    """Claude Code Agent Team session analysis tool."""
    pass


@main.command()
@click.option("--session-id", required=True, help="Session ID to collect")
@click.option(
    "--output", "output_dir", default=None,
    help="Output directory (default: next to session dir)",
)
def collect(session_id: str, output_dir: str | None) -> None:
    """Collect raw data from a Sub-agent mode session."""
    from pathlib import Path

    if output_dir is None:
        from analysis_tool.collect import _find_session_dir
        output_path = _find_session_dir(session_id) / "analysis"
    else:
        output_path = Path(output_dir)

    analysis_dir = collect_session(session_id, output_path)
    click.echo(f"Raw data collected to {analysis_dir / 'raw'}")

    # Also run parser immediately
    events = parse_raw_dir(analysis_dir / "raw")
    events_file = analysis_dir / "events.jsonl"
    import json
    from dataclasses import asdict

    with open(events_file, "w") as f:
        for event in events:
            f.write(json.dumps(_event_to_dict(event), default=str) + "\n")
    click.echo(f"Parsed {len(events)} events to {events_file}")


def _event_to_dict(event: "UnifiedEvent") -> dict:  # type: ignore[no-any-unimported]
    """Serialize UnifiedEvent to a JSON-safe dict."""
    from analysis_tool.models import UnifiedEvent
    return {
        "event_id": str(event.event_id),
        "timestamp": event.timestamp.isoformat(),
        "agent_id": event.agent_id,
        "source": event.source.value,
        "type": event.type.value,
        "parent_id": str(event.parent_id) if event.parent_id else None,
        "data": event.data,
    }
```

- [ ] **Step 2: 用实际 session 测试**

```bash
uv run analysis-tool collect --session-id=<any-existing-session-id>
```
Expected: 看到 raw 数据采集成功、事件解析成功的输出。

- [ ] **Step 3: 验证产物**

```bash
ls ~/.claude/projects/*/<session-id>/analysis/raw/
ls ~/.claude/projects/*/<session-id>/analysis/events.jsonl
```
Expected: raw/ 目录存在且有 session.jsonl，events.jsonl 非空

- [ ] **Step 4: Commit**

```bash
git add src/analysis_tool/cli.py
git commit -m "feat: add CLI entry point with collect command"
```

---

## Phase 2: 分析命令（状态机 + 协作图 + 基础报告）

### Task 7: 任务状态机

**Files:**
- Create: `src/analysis_tool/state_machine.py`
- Create: `tests/test_state_machine.py`

- [ ] **Step 1: 写 failing tests**

```python
# tests/test_state_machine.py
from datetime import datetime, timezone

from analysis_tool.models import EventType, EventSource, UnifiedEvent
from analysis_tool.state_machine import (
    build_state_machines,
    detect_anomalies,
    StateTransition,
    Anomaly,
)


def make_event(**kwargs: object) -> UnifiedEvent:
    defaults: dict[str, object] = {
        "timestamp": datetime(2026, 6, 18, 12, 0, 0, tzinfo=timezone.utc),
        "agent_id": "agent-1",
        "source": EventSource.TRANSCRIPT,
        "type": EventType.TASK_CREATE,
        "data": {"task_id": "task-1", "subject": "test"},
    }
    defaults.update(kwargs)
    return UnifiedEvent.create(**defaults)  # type: ignore[arg-type]


def test_build_state_machines_tracks_transitions():
    events = [
        make_event(
            type=EventType.TASK_CREATE,
            data={"task_id": "t1", "subject": "do X"},
        ),
        make_event(
            type=EventType.TASK_UPDATE,
            timestamp=datetime(2026, 6, 18, 12, 1, 0, tzinfo=timezone.utc),
            data={"task_id": "t1", "new_status": "in_progress", "old_status": "", "owner": "agent-1"},
        ),
        make_event(
            type=EventType.TASK_UPDATE,
            timestamp=datetime(2026, 6, 18, 12, 2, 0, tzinfo=timezone.utc),
            data={"task_id": "t1", "new_status": "completed", "old_status": "", "owner": "agent-1"},
        ),
    ]
    machines = build_state_machines(events)
    assert "t1" in machines
    transitions = machines["t1"]
    assert len(transitions) == 3
    assert transitions[0].status == "pending"
    assert transitions[1].status == "in_progress"
    assert transitions[2].status == "completed"


def test_detect_anomalies_finds_orphan_update():
    events = [
        make_event(
            type=EventType.TASK_UPDATE,
            data={"task_id": "orphan", "new_status": "in_progress", "old_status": "", "owner": ""},
        ),
    ]
    machines = build_state_machines(events)
    anomalies = detect_anomalies(machines)
    assert len(anomalies) >= 1
    assert any(a.kind == "orphan_update" for a in anomalies)


def test_detect_anomalies_finds_stuck_in_progress():
    events = [
        make_event(
            type=EventType.TASK_CREATE,
            data={"task_id": "t1", "subject": "do X"},
        ),
        make_event(
            type=EventType.TASK_UPDATE,
            timestamp=datetime(2026, 6, 18, 12, 1, 0, tzinfo=timezone.utc),
            data={"task_id": "t1", "new_status": "in_progress", "old_status": "", "owner": "agent-1"},
        ),
    ]
    machines = build_state_machines(events)
    anomalies = detect_anomalies(machines)
    assert any(a.kind == "stuck_in_progress" for a in anomalies)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_state_machine.py -v
```
Expected: FAIL

- [ ] **Step 3: 实现 state_machine.py**

```python
# src/analysis_tool/state_machine.py
from dataclasses import dataclass
from datetime import datetime

from analysis_tool.models import EventType, UnifiedEvent


@dataclass
class StateTransition:
    task_id: str
    status: str
    agent_id: str
    timestamp: datetime


@dataclass
class Anomaly:
    task_id: str
    kind: str  # "orphan_update", "stuck_in_progress", "missing_dependency"
    detail: str


def build_state_machines(events: list[UnifiedEvent]) -> dict[str, list[StateTransition]]:
    """Reconstruct task state machines from create/update events."""
    machines: dict[str, list[StateTransition]] = {}

    task_events = [
        e for e in events
        if e.type in (EventType.TASK_CREATE, EventType.TASK_UPDATE)
    ]
    task_events.sort(key=lambda e: e.timestamp)

    for event in task_events:
        task_id = event.data.get("task_id", "")
        if not task_id:
            continue

        if task_id not in machines:
            machines[task_id] = []

        if event.type == EventType.TASK_CREATE:
            machines[task_id].append(StateTransition(
                task_id=task_id,
                status="pending",
                agent_id=event.agent_id,
                timestamp=event.timestamp,
            ))
        elif event.type == EventType.TASK_UPDATE:
            new_status = event.data.get("new_status", "")
            machines[task_id].append(StateTransition(
                task_id=task_id,
                status=new_status,
                agent_id=event.agent_id,
                timestamp=event.timestamp,
            ))

    return machines


def detect_anomalies(machines: dict[str, list[StateTransition]]) -> list[Anomaly]:
    """Detect anomalies in task state machines."""
    anomalies: list[Anomaly] = []

    for task_id, transitions in machines.items():
        has_create = any(t.status == "pending" for t in transitions)
        if not has_create:
            anomalies.append(Anomaly(
                task_id=task_id,
                kind="orphan_update",
                detail=f"Task {task_id} has updates but no create event",
            ))

        final_status = transitions[-1].status if transitions else "unknown"
        if final_status == "in_progress":
            anomalies.append(Anomaly(
                task_id=task_id,
                kind="stuck_in_progress",
                detail=f"Task {task_id} ended in in_progress without completion",
            ))

    return anomalies
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_state_machine.py -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/analysis_tool/state_machine.py tests/test_state_machine.py
git commit -m "feat: add task state machine reconstruction and anomaly detection"
```

### Task 8: 协作图

**Files:**
- Create: `src/analysis_tool/graph.py`
- Create: `tests/test_graph.py`

- [ ] **Step 1: 写 failing tests**

```python
# tests/test_graph.py
from datetime import datetime, timezone

from analysis_tool.models import EventType, EventSource, UnifiedEvent
from analysis_tool.graph import build_collaboration_graph, to_mermaid


def make_msg_event(from_agent: str, to_agent: str, ts_offset: int = 0) -> UnifiedEvent:
    return UnifiedEvent.create(
        timestamp=datetime(2026, 6, 18, 12, 0, ts_offset, tzinfo=timezone.utc),
        agent_id=from_agent,
        source=EventSource.TRANSCRIPT,
        type=EventType.MESSAGE_SEND,
        data={"from": from_agent, "to": to_agent, "summary": "test msg", "message_type": "task_assignment"},
    )


def test_build_collaboration_graph():
    events = [
        make_msg_event("lead", "agent-a", 0),
        make_msg_event("lead", "agent-b", 1),
        make_msg_event("agent-a", "lead", 2),
    ]
    graph = build_collaboration_graph(events)

    assert "lead" in graph.nodes
    assert "agent-a" in graph.nodes
    assert "agent-b" in graph.nodes
    assert len(graph.edges) == 3

    lead_to_a = [e for e in graph.edges if e.from_agent == "lead" and e.to_agent == "agent-a"]
    assert len(lead_to_a) == 1
    assert lead_to_a[0].message_count == 1


def test_to_mermaid_generates_valid_syntax():
    events = [
        make_msg_event("lead", "agent-a", 0),
    ]
    graph = build_collaboration_graph(events)
    mmd = to_mermaid(graph)

    assert "graph TD" in mmd or "graph LR" in mmd
    assert "lead" in mmd
    assert "agent-a" in mmd
    assert "-->" in mmd
    assert "1 msg" in mmd
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_graph.py -v
```
Expected: FAIL

- [ ] **Step 3: 实现 graph.py**

```python
# src/analysis_tool/graph.py
from dataclasses import dataclass, field

from analysis_tool.models import EventType, UnifiedEvent


@dataclass
class GraphEdge:
    from_agent: str
    to_agent: str
    message_count: int = 0
    message_types: set[str] = field(default_factory=set)


@dataclass
class Graph:
    nodes: set[str] = field(default_factory=set)
    edges: list[GraphEdge] = field(default_factory=list)


def build_collaboration_graph(events: list[UnifiedEvent]) -> Graph:
    """Extract agent communication graph from message_send events."""
    graph = Graph()

    # Aggregate edges
    edge_map: dict[tuple[str, str], GraphEdge] = {}

    for event in events:
        if event.type != EventType.MESSAGE_SEND:
            continue

        from_agent = event.data.get("from", event.agent_id)
        to_agent = event.data.get("to", "")

        if not from_agent or not to_agent:
            continue

        graph.nodes.add(from_agent)
        graph.nodes.add(to_agent)

        key = (from_agent, to_agent)
        if key not in edge_map:
            edge_map[key] = GraphEdge(from_agent=from_agent, to_agent=to_agent)

        edge = edge_map[key]
        edge.message_count += 1
        msg_type = event.data.get("message_type", "message")
        edge.message_types.add(msg_type)

    graph.edges = list(edge_map.values())
    return graph


def to_mermaid(graph: Graph) -> str:
    """Render collaboration graph as Mermaid markup."""
    lines = ["graph TD"]

    # Generate node IDs (sanitize agent names)
    def node_id(name: str) -> str:
        return name.replace("-", "").replace("@", "").replace(".", "")

    for node in sorted(graph.nodes):
        label = node.split("@")[0] if "@" in node else node
        lines.append(f"    {node_id(node)}[{label}]")

    for edge in graph.edges:
        types = ", ".join(sorted(edge.message_types))
        lines.append(
            f"    {node_id(edge.from_agent)} -->|"
            f"{edge.message_count} msg [{types}]| "
            f"{node_id(edge.to_agent)}"
        )

    return "\n".join(lines) + "\n"
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_graph.py -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/analysis_tool/graph.py tests/test_graph.py
git commit -m "feat: add collaboration graph generation with Mermaid output"
```

### Task 9: 将 analyze 子命令接入 CLI

**Files:**
- Modify: `src/analysis_tool/cli.py`

- [ ] **Step 1: 添加 analyze 命令**

```python
# 追加到 cli.py

@main.command()
@click.option("--session-dir", required=True, help="Path to analysis/ directory")
def analyze(session_dir: str) -> None:
    """Analyze a collected session and generate reports."""
    from pathlib import Path

    analysis_dir = Path(session_dir)
    raw_dir = analysis_dir / "raw"

    if not raw_dir.is_dir():
        click.echo(f"Error: raw/ directory not found in {analysis_dir}", err=True)
        raise SystemExit(1)

    # Parse events
    events = parse_raw_dir(raw_dir)
    click.echo(f"Parsed {len(events)} events")

    # Write unified event stream
    import json
    events_file = analysis_dir / "events.jsonl"
    with open(events_file, "w") as f:
        for event in events:
            f.write(json.dumps(_event_to_dict(event), default=str) + "\n")

    # Generate state machine report
    from analysis_tool.state_machine import build_state_machines, detect_anomalies
    machines = build_state_machines(events)
    anomalies = detect_anomalies(machines)

    click.echo(f"\nTask State Machines: {len(machines)} tasks")
    for task_id, transitions in machines.items():
        path_str = " → ".join(t.status for t in transitions)
        click.echo(f"  {task_id}: {path_str}")

    if anomalies:
        click.echo(f"\nAnomalies ({len(anomalies)}):")
        for a in anomalies:
            click.echo(f"  [{a.kind}] {a.detail}")

    # Generate collaboration graph
    from analysis_tool.graph import build_collaboration_graph, to_mermaid
    graph = build_collaboration_graph(events)
    mermaid = to_mermaid(graph)

    graph_file = analysis_dir / "graph.mermaid"
    graph_file.write_text(mermaid)
    click.echo(f"\nCollaboration graph written to {graph_file}")
    click.echo(f"  Nodes: {len(graph.nodes)}, Edges: {len(graph.edges)}")

    # Generate report
    from analysis_tool.comparator import _session_summary
    summary = _session_summary(events)
    report_file = analysis_dir / "report.md"
    report_file.write_text(summary)
    click.echo(f"\nReport written to {report_file}")

    click.echo("\nDone.")
```

- [ ] **Step 2: 用实际采集的 session 测试**

```bash
uv run analysis-tool analyze --session-dir=<path-to-analysis-dir>
```
Expected: 看到事件计数、状态机、协作图和报告输出

- [ ] **Step 3: 验证输出文件**

```bash
ls <analysis-dir>/events.jsonl <analysis-dir>/graph.mermaid <analysis-dir>/report.md
```
Expected: 三个文件都存在且非空

- [ ] **Step 4: Commit**

```bash
git add src/analysis_tool/cli.py
git commit -m "feat: add analyze command with state machine, graph, and report output"
```

---

## Phase 3: watch 命令（Agent Team 模式 kqueue 监控）

### Task 10: kqueue 文件监控

**Files:**
- Create: `src/analysis_tool/watch.py`
- Create: `tests/test_watch.py`

- [ ] **Step 1: 写 failing test — 文件变更触发事件记录**

```python
# tests/test_watch.py
import json
import threading
import time
from pathlib import Path

from analysis_tool.watch import watch_teams, KqueueWatcher


def test_kqueue_watcher_detects_file_write(tmp_path: Path):
    """A write to a watched file should be captured."""
    inbox_dir = tmp_path / "inboxes"
    inbox_dir.mkdir()
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()

    output_log = tmp_path / "team-events.jsonl"
    stop_event = threading.Event()

    watcher = KqueueWatcher(
        inbox_dir=inbox_dir,
        tasks_dir=tasks_dir,
        output_path=output_log,
        poll_interval=0.1,  # fast poll for testing
    )

    # Start in background thread
    t = threading.Thread(target=watcher.run, args=(stop_event,), daemon=True)
    t.start()

    # Give it time to initialize
    time.sleep(0.2)

    # Write a file to trigger event
    (inbox_dir / "agent-x.json").write_text(
        json.dumps([{"from": "lead", "summary": "hello", "read": False}])
    )

    # Wait for event capture
    time.sleep(0.3)

    stop_event.set()
    t.join(timeout=2)

    # Verify output
    assert output_log.exists()
    lines = output_log.read_text().strip().split("\n")
    assert len(lines) >= 1

    first_event = json.loads(lines[0])
    assert first_event["kind"] == "mailbox_snapshot"
    assert "agent-x.json" in first_event["path"]
    assert len(first_event["content"]) == 1
    assert first_event["content"][0]["from"] == "lead"


def test_kqueue_watcher_poll_catchup(tmp_path: Path):
    """If kqueue misses an event, poll should catch it."""
    inbox_dir = tmp_path / "inboxes"
    inbox_dir.mkdir()
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()

    # Pre-create a file before watcher starts
    (inbox_dir / "agent-y.json").write_text(
        json.dumps([{"from": "lead", "summary": "pre-existing", "read": True}])
    )

    output_log = tmp_path / "team-events.jsonl"
    stop_event = threading.Event()

    watcher = KqueueWatcher(
        inbox_dir=inbox_dir,
        tasks_dir=tasks_dir,
        output_path=output_log,
        poll_interval=0.1,
    )

    t = threading.Thread(target=watcher.run, args=(stop_event,), daemon=True)
    t.start()

    time.sleep(0.5)

    stop_event.set()
    t.join(timeout=2)

    lines = output_log.read_text().strip().split("\n")
    # Should have captured the pre-existing file via initial scan or poll
    assert len(lines) >= 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_watch.py -v
```
Expected: FAIL

- [ ] **Step 3: 实现 watch.py**

```python
# src/analysis_tool/watch.py
import json
import os
import select
import threading
import time
from datetime import datetime, timezone
from pathlib import Path


class KqueueWatcher:
    """Monitor directory trees using kqueue for per-file write notifications."""

    def __init__(
        self,
        inbox_dir: Path,
        tasks_dir: Path,
        output_path: Path,
        poll_interval: float = 5.0,
    ) -> None:
        self.inbox_dir = inbox_dir
        self.tasks_dir = tasks_dir
        self.output_path = output_path
        self.poll_interval = poll_interval
        self._kq = select.kqueue()
        self._fd_to_path: dict[int, Path] = {}
        self._last_snapshot: dict[str, object] = {}

    def run(self, stop_event: threading.Event) -> None:
        self._scan_and_register()
        self._initial_snapshot()

        while not stop_event.is_set():
            # Wait for events with timeout (for periodic poll)
            timeout = min(self.poll_interval, 1.0)
            try:
                events = self._kq.control(None, 128, timeout)
            except OSError:
                break

            if events:
                changed_paths: set[Path] = set()
                for event in events:
                    fd = event.ident
                    path = self._fd_to_path.get(fd)
                    if path is None:
                        # Could be directory event - re-scan
                        self._scan_and_register()
                        continue

                    if event.filter == select.KQ_FILTER_VNODE:
                        changed_paths.add(path)
                        # If directory changed, rescan for new files
                        if path.is_dir():
                            self._scan_and_register()

                # Read content of changed files
                for path in changed_paths:
                    if path.is_file():
                        self._capture_snapshot(path)

            # Periodic poll as safety net
            if not events or self._time_for_poll():
                self._poll_catchup()

    def _scan_and_register(self) -> None:
        """Scan monitored directories and register kqueue for all files + dirs."""
        all_dirs = [self.inbox_dir, self.tasks_dir]
        for base_dir in all_dirs:
            if not base_dir.is_dir():
                continue
            # Monitor the directory itself for new files
            self._register(base_dir)
            for f in base_dir.iterdir():
                self._register(f)

    def _register(self, path: Path) -> None:
        """Register a single path with kqueue if not already tracked."""
        try:
            fd = os.open(str(path), os.O_RDONLY)
        except OSError:
            return

        if fd in self._fd_to_path:
            os.close(fd)
            return

        self._fd_to_path[fd] = path
        ev = select.kevent(
            fd,
            filter=select.KQ_FILTER_VNODE,
            flags=select.KQ_EV_ADD | select.KQ_EV_CLEAR,
            fflags=select.KQ_NOTE_WRITE | select.KQ_NOTE_EXTEND | select.KQ_NOTE_DELETE,
        )
        self._kq.control([ev], 0)

    def _initial_snapshot(self) -> None:
        """Capture initial state of all files for later diff."""
        for base_dir in [self.inbox_dir, self.tasks_dir]:
            if not base_dir.is_dir():
                continue
            for f in base_dir.iterdir():
                if f.is_file() and f.suffix == ".json":
                    self._capture_snapshot(f)

    def _capture_snapshot(self, path: Path) -> None:
        """Read file content and write a snapshot event."""
        try:
            content_raw = path.read_text()
            content = json.loads(content_raw)
        except (OSError, json.JSONDecodeError):
            return

        kind = "mailbox_snapshot" if "inboxes" in str(path) else "task_snapshot"

        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "path": str(path),
            "kind": kind,
            "content": content,
        }

        with open(self.output_path, "a") as f:
            f.write(json.dumps(event, default=str) + "\n")

        # Update snapshot cache for diff
        self._last_snapshot[str(path)] = {
            "timestamp": event["timestamp"],
            "content": json.dumps(content, sort_keys=True),
        }

    def _time_for_poll(self) -> bool:
        """Check if poll interval has elapsed since last poll."""
        # Simple implementation: always poll when called after a timeout wake
        return True

    def _poll_catchup(self) -> None:
        """Scan all files and capture any that differ from last known snapshot."""
        for base_dir in [self.inbox_dir, self.tasks_dir]:
            if not base_dir.is_dir():
                continue
            for f in base_dir.iterdir():
                if not f.is_file() or f.suffix != ".json":
                    continue
                try:
                    current = json.dumps(json.loads(f.read_text()), sort_keys=True)
                except (OSError, json.JSONDecodeError):
                    continue

                cached = self._last_snapshot.get(str(f))
                if cached is None or cached["content"] != current:
                    self._capture_snapshot(f)


def watch_teams(
    team_name: str,
    output_dir: Path,
    stop_event: threading.Event,
) -> None:
    """Monitor inboxes and tasks for a given team name.

    Writes team-events.jsonl to output_dir/raw/.
    """
    home = Path.home()
    inbox_dir = home / ".claude" / "teams" / team_name / "inboxes"
    tasks_dir = home / ".claude" / "tasks" / team_name

    raw_dir = output_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    output_path = raw_dir / "team-events.jsonl"

    watcher = KqueueWatcher(
        inbox_dir=inbox_dir,
        tasks_dir=tasks_dir,
        output_path=output_path,
    )
    watcher.run(stop_event)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_watch.py -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/analysis_tool/watch.py tests/test_watch.py
git commit -m "feat: add kqueue-based file monitoring for Agent Team mode"
```

### Task 11: CLI watch 命令

**Files:**
- Modify: `src/analysis_tool/cli.py`

- [ ] **Step 1: 添加 watch 命令**

```python
# 追加到 cli.py
import signal
import threading


@main.command()
@click.option("--team-name", required=True, help="Team name (same as session ID)")
@click.option("--output", "output_dir", default=None, help="Output directory for analysis data")
def watch(team_name: str, output_dir: str | None) -> None:
    """Monitor Agent Team communication files in real-time.

    Runs until interrupted (Ctrl+C). Outputs team-events.jsonl.
    """
    from pathlib import Path
    from analysis_tool.watch import watch_teams

    if output_dir is None:
        output_path = Path.home() / ".claude" / "agent-team-analysis" / team_name
    else:
        output_path = Path(output_dir)

    stop_event = threading.Event()

    # Handle SIGINT/SIGTERM gracefully
    def _handle_signal(signum: int, frame: object) -> None:
        click.echo("\nStopping watcher...")
        stop_event.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    click.echo(f"Watching team '{team_name}'... (Ctrl+C to stop)")
    click.echo(f"Output: {output_path / 'raw' / 'team-events.jsonl'}")

    watch_teams(team_name, output_path, stop_event)

    click.echo(f"Done. Events written to {output_path / 'raw' / 'team-events.jsonl'}")
```

- [ ] **Step 2: 手动启动 watch 测试**

在 Agent Team session 启动前运行：
```bash
uv run analysis-tool watch --team-name=<team-name>
```
然后在另一个终端启动 Agent Team session，验证 `team-events.jsonl` 产生事件。

- [ ] **Step 3: Commit**

```bash
git add src/analysis_tool/cli.py
git commit -m "feat: add watch CLI command for Agent Team monitoring"
```

---

## Phase 4: 对比分析

### Task 12: comparator 模块

**Files:**
- Create: `src/analysis_tool/comparator.py`
- Create: `tests/test_comparator.py`

- [ ] **Step 1: 写 failing tests**

```python
# tests/test_comparator.py
from datetime import datetime, timezone

from analysis_tool.models import EventType, EventSource, UnifiedEvent
from analysis_tool.comparator import compare, ComparisonReport, _session_summary


def test_compare_returns_report():
    """compare() should take two session dirs and return a ComparisonReport."""
    events_a = [
        UnifiedEvent.create(
            timestamp=datetime(2026, 6, 18, 12, 0, 0, tzinfo=timezone.utc),
            agent_id="main",
            source=EventSource.TRANSCRIPT,
            type=EventType.AGENT_SPAWN,
            data={"child_agent_id": "a0", "tool_use_id": "c1"},
        ),
        UnifiedEvent.create(
            timestamp=datetime(2026, 6, 18, 12, 1, 0, tzinfo=timezone.utc),
            agent_id="a0",
            source=EventSource.TRANSCRIPT,
            type=EventType.AGENT_COMPLETE,
            data={"tokens_used": 1000, "duration_ms": 50000},
        ),
    ]
    events_b = [
        UnifiedEvent.create(
            timestamp=datetime(2026, 6, 18, 12, 0, 0, tzinfo=timezone.utc),
            agent_id="lead",
            source=EventSource.TRANSCRIPT,
            type=EventType.MESSAGE_SEND,
            data={"from": "lead", "to": "agent-a", "summary": "task", "message_type": "task_assignment"},
        ),
        UnifiedEvent.create(
            timestamp=datetime(2026, 6, 18, 12, 1, 0, tzinfo=timezone.utc),
            agent_id="lead",
            source=EventSource.TRANSCRIPT,
            type=EventType.MESSAGE_SEND,
            data={"from": "agent-a", "to": "lead", "summary": "result", "message_type": "message"},
        ),
    ]

    report = compare(events_a, "sub-agent", events_b, "agent-team")

    assert isinstance(report, ComparisonReport)
    assert report.mode_a == "sub-agent"
    assert report.mode_b == "agent-team"
    assert report.agent_count_a == 2  # main + a0
    assert report.agent_count_b == 2  # lead + agent-a
    assert report.message_count_a == 0
    assert report.message_count_b == 2


def test_session_summary_is_markdown():
    events = [
        UnifiedEvent.create(
            timestamp=datetime(2026, 6, 18, 12, 0, 0, tzinfo=timezone.utc),
            agent_id="main",
            source=EventSource.TRANSCRIPT,
            type=EventType.AGENT_MESSAGE,
            data={"role": "user", "content_summary": "hello", "token_usage": {}, "tool_calls": []},
        ),
    ]
    md = _session_summary(events)
    assert isinstance(md, str)
    assert "# " in md  # has headings
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_comparator.py -v
```
Expected: FAIL

- [ ] **Step 3: 实现 comparator.py**

```python
# src/analysis_tool/comparator.py
from dataclasses import dataclass, field

from analysis_tool.models import EventType, UnifiedEvent


@dataclass
class ComparisonReport:
    mode_a: str
    mode_b: str
    agent_count_a: int = 0
    agent_count_b: int = 0
    message_count_a: int = 0
    message_count_b: int = 0
    spawn_count_a: int = 0
    spawn_count_b: int = 0
    total_tokens_a: int = 0
    total_tokens_b: int = 0
    duration_seconds_a: float = 0.0
    duration_seconds_b: float = 0.0
    sections: list[str] = field(default_factory=list)


def compare(
    events_a: list[UnifiedEvent],
    mode_a: str,
    events_b: list[UnifiedEvent],
    mode_b: str,
) -> ComparisonReport:
    """Compare two sessions and produce a structured report."""
    report = ComparisonReport(mode_a=mode_a, mode_b=mode_b)

    # Agent counts (unique agent_ids)
    agents_a = {e.agent_id for e in events_a}
    agents_b = {e.agent_id for e in events_b}
    report.agent_count_a = len(agents_a)
    report.agent_count_b = len(agents_b)

    # Message counts
    report.message_count_a = sum(1 for e in events_a if e.type == EventType.MESSAGE_SEND)
    report.message_count_b = sum(1 for e in events_b if e.type == EventType.MESSAGE_SEND)

    # Spawn counts
    report.spawn_count_a = sum(1 for e in events_a if e.type == EventType.AGENT_SPAWN)
    report.spawn_count_b = sum(1 for e in events_b if e.type == EventType.AGENT_SPAWN)

    # Token totals (from agent_complete events + agent_message usage)
    for events, attr in [(events_a, "total_tokens_a"), (events_b, "total_tokens_b")]:
        total = 0
        for e in events:
            if e.type == EventType.AGENT_COMPLETE:
                total += e.data.get("tokens_used", 0)
            elif e.type == EventType.AGENT_MESSAGE:
                usage = e.data.get("token_usage", {})
                if isinstance(usage, dict):
                    total += usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
        setattr(report, attr, total)

    # Duration
    if events_a:
        t0 = events_a[0].timestamp
        t1 = events_a[-1].timestamp
        report.duration_seconds_a = (t1 - t0).total_seconds()
    if events_b:
        t0 = events_b[0].timestamp
        t1 = events_b[-1].timestamp
        report.duration_seconds_b = (t1 - t0).total_seconds()

    return report


def _session_summary(events: list[UnifiedEvent]) -> str:
    """Generate a Markdown summary of a single session."""
    agent_ids = sorted({e.agent_id for e in events})
    spawns = sum(1 for e in events if e.type == EventType.AGENT_SPAWN)
    msgs = sum(1 for e in events if e.type == EventType.MESSAGE_SEND)
    tasks = sum(1 for e in events if e.type == EventType.TASK_CREATE)

    lines = [
        "# Session Analysis Report",
        "",
        f"**Agents**: {len(agent_ids)} ({', '.join(agent_ids[:10])})",
        f"**Agent spawns**: {spawns}",
        f"**Messages sent**: {msgs}",
        f"**Tasks created**: {tasks}",
        f"**Total events**: {len(events)}",
        "",
    ]

    if events:
        duration = (events[-1].timestamp - events[0].timestamp).total_seconds()
        lines.append(f"**Duration**: {duration:.1f}s")
        lines.append(f"**Time range**: {events[0].timestamp.isoformat()} → {events[-1].timestamp.isoformat()}")

    return "\n".join(lines) + "\n"
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_comparator.py -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/analysis_tool/comparator.py tests/test_comparator.py
git commit -m "feat: add comparator module for Sub-agent vs Agent Team analysis"
```

---

## Phase 5: 时间线 + HTML 渲染

### Task 13: 时间线数据 + HTML

**Files:**
- Create: `src/analysis_tool/timeline.py`
- Create: `src/analysis_tool/templates/timeline.html.j2`
- Create: `tests/test_timeline.py`

- [ ] **Step 1: 写 failing test — 时间线数据生成**

```python
# tests/test_timeline.py
from datetime import datetime, timezone

from analysis_tool.models import EventType, EventSource, UnifiedEvent
from analysis_tool.timeline import build_timeline_data


def test_build_timeline_data_groups_by_agent():
    events = [
        UnifiedEvent.create(
            timestamp=datetime(2026, 6, 18, 12, 0, 0, tzinfo=timezone.utc),
            agent_id="main",
            source=EventSource.TRANSCRIPT,
            type=EventType.AGENT_SPAWN,
            data={"child_agent_id": "a0", "tool_use_id": "c1"},
        ),
        UnifiedEvent.create(
            timestamp=datetime(2026, 6, 18, 12, 0, 30, tzinfo=timezone.utc),
            agent_id="a0",
            source=EventSource.TRANSCRIPT,
            type=EventType.AGENT_MESSAGE,
            data={"role": "assistant", "content_summary": "hello", "token_usage": {}, "tool_calls": []},
        ),
    ]

    data = build_timeline_data(events)

    assert "agents" in data
    assert len(data["agents"]) == 2  # main + a0
    assert "events" in data
    assert len(data["events"]) == 2

    agent_ids = [a["id"] for a in data["agents"]]
    assert "main" in agent_ids
    assert "a0" in agent_ids

    # Check first event has spawn link info
    spawn_ev = data["events"][0]
    assert spawn_ev["type"] == "agent_spawn"
    assert "parent_id" in spawn_ev
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_timeline.py -v
```
Expected: FAIL

- [ ] **Step 3: 实现 timeline.py**

```python
# src/analysis_tool/timeline.py
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from analysis_tool.models import UnifiedEvent


def build_timeline_data(events: list[UnifiedEvent]) -> dict:
    """Build JSON-serializable data for the D3.js timeline visualization."""
    # Discover unique agents
    agent_ids = sorted({e.agent_id for e in events})
    agents = [{"id": aid, "label": aid.split("@")[0] if "@" in aid else aid}
              for aid in agent_ids]
    agent_index = {aid: i for i, aid in enumerate(agent_ids)}

    # Compute time range
    if events:
        t0 = events[0].timestamp
        t1 = events[-1].timestamp
        total_seconds = max((t1 - t0).total_seconds(), 1)
    else:
        t0 = events[0].timestamp if events else None
        total_seconds = 1

    # Serialize events
    event_list = []
    for e in events:
        offset_seconds = (e.timestamp - t0).total_seconds() if t0 else 0
        event_list.append({
            "agent_id": e.agent_id,
            "agent_row": agent_index.get(e.agent_id, 0),
            "type": e.type.value,
            "timestamp": e.timestamp.isoformat(),
            "offset_seconds": offset_seconds,
            "offset_pct": (offset_seconds / total_seconds) * 100,
            "parent_id": str(e.parent_id) if e.parent_id else None,
            "data_summary": _summarize_data(e),
        })

    return {
        "agents": agents,
        "events": event_list,
        "total_seconds": total_seconds,
        "event_count": len(events),
    }


def _summarize_data(event: UnifiedEvent) -> str:
    """Produce a short human-readable summary of event data."""
    if event.type.value == "agent_spawn":
        return f"spawn → {event.data.get('child_agent_id', '?')}"
    if event.type.value == "message_send":
        return f"{event.data.get('from', '?')} → {event.data.get('to', '?')}: {event.data.get('summary', '')}"
    if event.type.value == "task_create":
        return f"task: {event.data.get('subject', '?')}"
    if event.type.value == "task_update":
        return f"→ {event.data.get('new_status', '?')}"
    if event.type.value == "agent_message":
        return event.data.get("content_summary", "")[:100]
    return ""


def render_html(data: dict, template_dir: Path, output_path: Path) -> None:
    """Render timeline data into an HTML file using the Jinja2 template."""
    env = Environment(loader=FileSystemLoader(str(template_dir)))
    template = env.get_template("timeline.html.j2")
    html = template.render(**data)
    output_path.write_text(html)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_timeline.py -v
```
Expected: PASS

- [ ] **Step 5: 创建 D3.js 时间线模板**

```html
<!-- src/analysis_tool/templates/timeline.html.j2 -->
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Agent Team Timeline</title>
<script src="https://d3js.org/d3.v7.min.js"></script>
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; margin: 20px; }
  .timeline { position: relative; }
  .agent-label { font-size: 12px; font-weight: 600; }
  .event-dot { cursor: pointer; }
  .event-dot:hover { stroke: #000; stroke-width: 2px; }
  .tooltip {
    position: absolute; background: #333; color: #fff; padding: 6px 10px;
    border-radius: 4px; font-size: 12px; pointer-events: none; opacity: 0;
    transition: opacity 0.2s; max-width: 300px;
  }
  .axis line, .axis path { stroke: #ccc; }
  .axis text { font-size: 10px; fill: #666; }
</style>
</head>
<body>
<h1>Agent Team Timeline</h1>
<p>{{ event_count }} events across {{ agents|length }} agents ({{ "%.1f"|format(total_seconds) }}s)</p>

<div class="timeline" id="timeline"></div>
<div class="tooltip" id="tooltip"></div>

<script>
const data = {{ agents|tojson }};
const events = {{ events|tojson }};
// Data is embedded via Jinja2 |tojson filter

const margin = { top: 20, right: 40, bottom: 30, left: 120 };
const rowHeight = 30;
const width = window.innerWidth - margin.left - margin.right - 40;
const height = data.length * rowHeight + margin.top + margin.bottom;

const svg = d3.select("#timeline")
  .append("svg")
  .attr("width", width + margin.left + margin.right)
  .attr("height", height);

const g = svg.append("g").attr("transform", `translate(${margin.left},${margin.top})`);

// Agent labels
g.selectAll(".agent-label")
  .data(data)
  .enter()
  .append("text")
  .attr("class", "agent-label")
  .attr("x", -10)
  .attr("y", (d, i) => i * rowHeight + rowHeight / 2)
  .attr("text-anchor", "end")
  .attr("dominant-baseline", "middle")
  .text(d => d.label);

// Time axis
const xScale = d3.scaleLinear().domain([0, 100]).range([0, width]);
const xAxis = d3.axisTop(xScale).ticks(10).tickFormat(d => d + "%");
g.append("g").attr("class", "axis").call(xAxis);

// Event dots
const colorMap = {
  agent_spawn: "#4CAF50",
  agent_complete: "#F44336",
  message_send: "#2196F3",
  message_read: "#03A9F4",
  task_create: "#FF9800",
  task_update: "#FFC107",
  agent_message: "#9E9E9E",
};

g.selectAll(".event-dot")
  .data(events)
  .enter()
  .append("circle")
  .attr("class", "event-dot")
  .attr("cx", d => xScale(d.offset_pct))
  .attr("cy", d => d.agent_row * rowHeight + rowHeight / 2)
  .attr("r", 5)
  .attr("fill", d => colorMap[d.type] || "#999")
  .on("mouseover", (evt, d) => {
    const tip = d3.select("#tooltip");
    tip.style("opacity", 1)
       .style("left", (evt.pageX + 10) + "px")
       .style("top", (evt.pageY - 20) + "px")
       .html(`<strong>${d.type}</strong><br>${d.data_summary}<br><small>${d.offset_seconds.toFixed(1)}s</small>`);
  })
  .on("mouseout", () => {
    d3.select("#tooltip").style("opacity", 0);
  });

// Spawn links
const spawnLinks = [];
events.forEach(e => {
  if (e.parent_id) {
    const parent = events.find(p => p.event_id === e.parent_id);
    if (parent) {
      spawnLinks.push({ source: parent, target: e });
    }
  }
});

g.selectAll(".spawn-link")
  .data(spawnLinks)
  .enter()
  .append("line")
  .attr("class", "spawn-link")
  .attr("x1", d => xScale(d.source.offset_pct))
  .attr("y1", d => d.source.agent_row * rowHeight + rowHeight / 2)
  .attr("x2", d => xScale(d.target.offset_pct))
  .attr("y2", d => d.target.agent_row * rowHeight + rowHeight / 2)
  .attr("stroke", "#ccc")
  .attr("stroke-dasharray", "4,2")
  .attr("stroke-width", 1);

// Legend
const legend = svg.append("g").attr("transform", `translate(${margin.left}, ${height + 10})`);
const types = Object.keys(colorMap);
types.forEach((t, i) => {
  legend.append("circle").attr("cx", i * 120).attr("cy", 0).attr("r", 5).attr("fill", colorMap[t]);
  legend.append("text").attr("x", i * 120 + 10).attr("y", 4).attr("font-size", "11px").text(t);
});
</script>
</body>
</html>
```

- [ ] **Step 6: 手动验证 HTML 输出**

```bash
uv run analysis-tool analyze --session-dir=<path>
open <analysis-dir>/timeline.html
```
Expected: 浏览器中看到时间线，hover 显示 tooltip

- [ ] **Step 7: Commit**

```bash
git add src/analysis_tool/timeline.py src/analysis_tool/templates/timeline.html.j2 tests/test_timeline.py
git commit -m "feat: add D3.js timeline visualization with HTML output"
```

### Task 14: analyze 命令集成时间线输出

**Files:**
- Modify: `src/analysis_tool/cli.py`

- [ ] **Step 1: 在 analyze 命令中追加时间线生成**

```python
# 在 analyze 函数末尾，report 写入之后添加：

    # Generate timeline
    from analysis_tool.timeline import build_timeline_data, render_html
    timeline_data = build_timeline_data(events)
    template_dir = Path(__file__).parent / "templates"
    timeline_file = analysis_dir / "timeline.html"
    render_html(timeline_data, template_dir, timeline_file)
    click.echo(f"Timeline written to {timeline_file}")
```

- [ ] **Step 2: 全链路测试**

```bash
uv run analysis-tool collect --session-id=<session-id>
uv run analysis-tool analyze --session-dir=<analysis-dir>
```
Expected: 产出 `events.jsonl`、`graph.mermaid`、`report.md`、`timeline.html` 四个文件。

- [ ] **Step 3: Commit**

```bash
git add src/analysis_tool/cli.py
git commit -m "feat: integrate timeline HTML generation into analyze command"
```

---

## 最终校验

- [ ] **Run full test suite**

```bash
uv run pytest tests/ -v
```
Expected: all tests PASS

- [ ] **Run ruff + pyright (strict mode)**

```bash
uv run ruff check src/ tests/
uv run pyright src/ tests/
```
Expected: both pass with no errors

- [ ] **Manual end-to-end test with real data**

```bash
# Sub-agent mode
uv run analysis-tool collect --session-id=<real-session-id>
uv run analysis-tool analyze --session-dir=<analysis-dir>
open <analysis-dir>/timeline.html

# Agent Team mode (requires active team session)
uv run analysis-tool watch --team-name=<team-name>
# ... run agent team session ...
# Ctrl+C to stop watch
uv run analysis-tool analyze --session-dir=<output-dir>
```
