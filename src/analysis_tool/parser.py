import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from analysis_tool.models import EventSource, EventType, UnifiedEvent


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
