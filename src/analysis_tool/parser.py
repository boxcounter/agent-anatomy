import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from analysis_tool.models import EventSource, EventType, UnifiedEvent


def parse_jsonl(path: Path) -> list[UnifiedEvent]:
    events: list[UnifiedEvent] = []
    tool_result_task_ids: dict[str, str] = {}  # tool_use_id -> taskId

    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)

            # Scan tool_result blocks for task IDs (from TaskCreate/TaskUpdate results)
            message = cast(dict[str, Any], entry.get("message", {}))
            content = cast(list[dict[str, Any]], message.get("content", []))
            for block in content:
                if block.get("type") == "tool_result":
                    tool_use_id: str = block.get("tool_use_id", "")
                    result_content = cast(list[dict[str, Any]], block.get("content", []))
                    for rc in result_content:
                        if rc.get("type") == "text":
                            try:
                                result_data = json.loads(rc.get("text", "{}"))
                                if "id" in result_data and tool_use_id:
                                    tool_result_task_ids[tool_use_id] = result_data["id"]
                            except (json.JSONDecodeError, TypeError):
                                pass

            parsed = _parse_jsonl_entry(entry)
            events.extend(parsed)

    # Backfill task_ids from tool_result map
    for i, event in enumerate(events):
        if event.type == EventType.TASK_CREATE and event.data.get("task_id") == "":
            tool_use_id = event.data.get("tool_use_id", "")
            if tool_use_id in tool_result_task_ids:
                events[i] = UnifiedEvent.create(
                    timestamp=event.timestamp,
                    agent_id=event.agent_id,
                    source=event.source,
                    type=event.type,
                    data={**event.data, "task_id": tool_result_task_ids[tool_use_id]},
                    parent_id=event.parent_id,
                )

    return events


def _parse_jsonl_entry(entry: dict[str, Any]) -> list[UnifiedEvent]:
    events: list[UnifiedEvent] = []
    agent_id: str = entry.get("agentId", "unknown")
    ts = datetime.fromisoformat(entry["timestamp"].replace("Z", "+00:00"))
    parent_uuid_raw = entry.get("parentUuid")
    parent_id = uuid.UUID(parent_uuid_raw) if parent_uuid_raw else None

    message: dict[str, Any] = cast(dict[str, Any], entry.get("message", {}))
    content: list[dict[str, Any]] = cast(list[dict[str, Any]], message.get("content", []))

    for block in content:
        if block.get("type") == "tool_use":
            name: str = block.get("name", "")
            tool_input: dict[str, Any] = cast(dict[str, Any], block.get("input", {}))
            tool_id: str = block.get("id", "")

            if name == "Agent":
                events.append(UnifiedEvent.create(
                    timestamp=ts,
                    agent_id=agent_id,
                    source=EventSource.TRANSCRIPT,
                    type=EventType.AGENT_SPAWN,
                    data={
                        "child_agent_id": "",
                        "tool_use_id": tool_id,
                        "agent_type": tool_input.get("subagent_type", "general-purpose"),
                        "description": tool_input.get("description", ""),
                    },
                    parent_id=parent_id,
                ))
            elif name == "SendMessage":
                msg_obj: dict[str, Any] = cast(dict[str, Any], tool_input.get("message", {}))
                events.append(UnifiedEvent.create(
                    timestamp=ts,
                    agent_id=agent_id,
                    source=EventSource.TRANSCRIPT,
                    type=EventType.MESSAGE_SEND,
                    data={
                        "from": agent_id,
                        "to": tool_input.get("to", ""),
                        "summary": tool_input.get("summary", ""),
                        "message_type": msg_obj.get("type", "message"),
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
                        "tool_use_id": tool_id,
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
                        "tool_use_id": tool_id,
                        "new_status": tool_input.get("status", ""),
                        "old_status": "",
                        "owner": tool_input.get("owner", ""),
                    },
                    parent_id=parent_id,
                ))

    # Also emit an agent_message event for the text content
    text_parts: list[str] = [
        b.get("text", "")
        for b in content
        if b.get("type") == "text"
    ]
    summary = " ".join(text_parts)[:200] if text_parts else ""

    if summary:
        tool_call_names: list[str] = [
            b.get("name", "")
            for b in content
            if b.get("type") == "tool_use"
        ]
        events.append(UnifiedEvent.create(
            timestamp=ts,
            agent_id=agent_id,
            source=EventSource.TRANSCRIPT,
            type=EventType.AGENT_MESSAGE,
            data={
                "role": message.get("role", "unknown"),
                "content_summary": summary,
                "token_usage": message.get("usage", {}),
                "tool_calls": tool_call_names,
            },
            parent_id=parent_id,
        ))

    return events


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

        if i == 0 and snap.get("kind") == "mailbox_snapshot":
            raw_content = snap.get("content", [])
            if isinstance(raw_content, list):
                content = cast(list[dict[str, Any]], raw_content)
                for msg in content:
                    events.append(UnifiedEvent.create(
                        timestamp=ts,
                        agent_id=str(Path(snap["path"]).stem),
                        source=EventSource.TEAM_EVENTS,
                        type=EventType.MESSAGE_SEND,
                        data={
                            "from": msg.get("from", ""),
                            "to": Path(snap["path"]).stem,
                            "summary": msg.get("summary", ""),
                            "message_type": "message",
                        },
                    ))

        if i > 0:
            prev = snapshots[i - 1]
            if snap.get("kind") == "mailbox_snapshot" and prev.get("kind") == "mailbox_snapshot":
                raw_prev = prev.get("content", [])
                raw_curr = snap.get("content", [])
                if isinstance(raw_prev, list) and isinstance(raw_curr, list):
                    _diff_mailbox(
                        cast(list[dict[str, Any]], raw_prev),
                        cast(list[dict[str, Any]], raw_curr),
                        ts, snap["path"], events,
                    )

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

    if len(curr_content) > len(prev_content):
        for msg in curr_content[len(prev_content):]:
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

    for prev_msg, curr_msg in zip(prev_content, curr_content):
        if (
            not prev_msg.get("read", False)
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
