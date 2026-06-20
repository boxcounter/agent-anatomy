# pyright: reportUnknownVariableType=false, reportUnknownMemberType=false
import json
import re
import uuid
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, cast

import click

from agent_anatomy.errors import ParseError, RawDataNotFoundError
from agent_anatomy.models import EventSource, EventType, UnifiedEvent

# TaskCreate returns plain text like "Task #4 created successfully: <subject>"
# — not JSON — so the id must be pulled out of the result text.
_TASK_CREATED_RE = re.compile(r"Task #(\d+) created", re.IGNORECASE)


def parse_jsonl(path: Path) -> list[UnifiedEvent]:
    events: list[UnifiedEvent] = []
    tool_result_task_ids: dict[str, str] = {}

    try:
        f = open(path)
    except OSError as exc:
        raise ParseError(str(path), str(exc)) from exc

    with f:
        for line_num, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as exc:
                click.echo(f"Warning: skipping malformed JSON on line {line_num} of {path}: {exc}", err=True)
                continue

            # Scan tool_result blocks for task IDs (from TaskCreate/TaskUpdate results).
            # Only list-form content carries tool_result blocks; string-form content
            # (e.g. sub-agent prompts) has none — but must still reach the entry
            # parser below, so don't `continue` past it here.
            raw_msg = entry.get("message", {})
            raw_cont = raw_msg.get("content", []) if isinstance(raw_msg, dict) else []
            for block in (raw_cont if isinstance(raw_cont, list) else []):
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    tool_use_id: str = block.get("tool_use_id", "")
                    if not tool_use_id:
                        continue
                    # tool_result content is either a plain string (e.g. the
                    # TaskCreate "Task #N created…" message) or a list of blocks.
                    result_content: Any = block.get("content", [])
                    texts: list[str] = []
                    if isinstance(result_content, str):
                        texts.append(result_content)
                    elif isinstance(result_content, list):
                        for rc in result_content:
                            if isinstance(rc, dict) and rc.get("type") == "text":
                                texts.append(cast(str, rc.get("text", "") or ""))
                    for text_val in texts:
                        try:
                            result_data = json.loads(text_val or "{}")  # type: ignore[reportUnknownArgumentType]
                            if "id" in result_data:
                                tool_result_task_ids[tool_use_id] = result_data["id"]
                        except (json.JSONDecodeError, TypeError):
                            pass
                        # Fallback: TaskCreate result is plain text "Task #N created…"
                        if tool_use_id not in tool_result_task_ids:
                            m = _TASK_CREATED_RE.search(text_val)
                            if m:
                                tool_result_task_ids[tool_use_id] = m.group(1)

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

    # Skip metadata entries that don't represent user/assistant messages
    entry_type = entry.get("type", "")
    if entry_type not in ("user", "assistant"):
        return events

    # Require timestamp — skip entries without it (e.g., mode/permission/file-history)
    ts_raw = entry.get("timestamp")
    if not ts_raw:
        return events

    agent_id: str = entry.get("agentId", entry.get("sessionId", "unknown"))
    ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
    parent_uuid_raw = entry.get("parentUuid")
    parent_id = uuid.UUID(parent_uuid_raw) if parent_uuid_raw else None

    message: Any = entry.get("message", {})
    if not isinstance(message, dict):
        return events
    message = cast(dict[str, Any], message)
    content: Any = message.get("content", [])

    # A turn's content may be a bare string instead of a list of blocks — this
    # is how sub-agent prompts (the instruction each agent is given) and other
    # plain-text turns are stored. Emit it as a text message so it isn't lost.
    is_meta = bool(entry.get("isMeta", False))

    if isinstance(content, str):
        text = content
        if text.strip():
            events.append(UnifiedEvent.create(
                timestamp=ts,
                agent_id=agent_id,
                source=EventSource.TRANSCRIPT,
                type=EventType.AGENT_MESSAGE,
                data={
                    "role": str(message.get("role", "unknown")),
                    "content_summary": text[:200],
                    "text": text,
                    "is_meta": is_meta,
                    "token_usage": message.get("usage", {}),
                    "tool_calls": [],
                },
                parent_id=parent_id,
            ))
        return events

    if not isinstance(content, list):
        return events
    content = cast(list[dict[str, Any]], content)

    try:
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                name: str = block.get("name", "")
                tool_input_raw: Any = block.get("input", {})
                if not isinstance(tool_input_raw, dict):
                    continue
                tool_input = cast(dict[str, Any], tool_input_raw)
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
                    msg_raw: Any = tool_input.get("message", {})
                    msg_type = "message"
                    if isinstance(msg_raw, dict):
                        msg_type = str(msg_raw.get("type", "message"))  # type: ignore[reportUnknownArgumentType]
                    events.append(UnifiedEvent.create(
                        timestamp=ts,
                        agent_id=agent_id,
                        source=EventSource.TRANSCRIPT,
                        type=EventType.MESSAGE_SEND,
                        data={
                            "from": agent_id,
                            "to": str(tool_input.get("to", "")),
                            "summary": str(tool_input.get("summary", "")),
                            "message_type": msg_type,
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
                            "subject": str(tool_input.get("subject", "")),
                            "description": str(tool_input.get("description", "")),
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
                            "task_id": str(tool_input.get("taskId", "")),
                            "tool_use_id": tool_id,
                            "new_status": str(tool_input.get("status", "")),
                            "old_status": "",
                            "owner": str(tool_input.get("owner", "")),
                        },
                        parent_id=parent_id,
                    ))

        # Also emit an agent_message event for the text content
        text_parts: list[str] = [
            b.get("text", "")
            for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        ]

        # A workflow agent that returns via `schema:` does so through the
        # StructuredOutput tool — its result lives in the tool_use *input*, not
        # in a text block. Render it so the agent's actual output (the angles,
        # verdict, synthesis…) reaches the per-agent transcript instead of just
        # the "I returned it via structured output" postamble.
        structured_parts: list[str] = []
        for b in content:
            if not (isinstance(b, dict) and b.get("type") == "tool_use"
                    and b.get("name") == "StructuredOutput"):
                continue
            payload: Any = b.get("input", {})
            try:
                rendered = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
            except (TypeError, ValueError):
                rendered = "(unserializable structured output)"
            structured_parts.append(f"**Structured output:**\n\n```json\n{rendered}\n```")

        full_text = "\n\n".join([*(p for p in text_parts if p), *structured_parts])
        if text_parts:
            summary = " ".join(text_parts)[:200]
        elif structured_parts:
            summary = "(structured output)"
        else:
            summary = ""

        if full_text:
            tool_call_names: list[str] = [
                b.get("name", "")
                for b in content
                if isinstance(b, dict) and b.get("type") == "tool_use"
            ]
            events.append(UnifiedEvent.create(
                timestamp=ts,
                agent_id=agent_id,
                source=EventSource.TRANSCRIPT,
                type=EventType.AGENT_MESSAGE,
                data={
                    "role": str(message.get("role", "unknown")),
                    "content_summary": summary,
                    "text": full_text,  # full untruncated text — the authoritative store
                    "is_meta": is_meta,
                    "token_usage": message.get("usage", {}),
                    "tool_calls": tool_call_names,
                },
                parent_id=parent_id,
            ))
    except Exception:
        # Skip entries that don't match expected format
        pass

    return events


def parse_raw_dir(raw_dir: Path) -> list[UnifiedEvent]:
    """Parse all raw data in a session analysis/raw directory into unified events.

    Linking is done in two phases. A spawn's `tool_use` call may live in *any*
    transcript — a sub-agent that spawns another sub-agent records the call in
    its own sidechain. So we first parse session.jsonl plus *every* sidechain
    into one complete event set, then resolve `child_agent_id` against it. (An
    earlier version linked while interleaving sidechain parsing in filename
    order, so nested spawns whose parent sidechain wasn't loaded yet were
    silently orphaned.)
    """
    all_events: list[UnifiedEvent] = []

    session_jsonl = raw_dir / "session.jsonl"
    if not session_jsonl.exists():
        raise RawDataNotFoundError(str(raw_dir))

    # Phase 1: parse session + all sidechains into one complete event set.
    all_events.extend(parse_jsonl(session_jsonl))

    subagents_dir = raw_dir / "subagents"
    tool_use_to_child: dict[str, str] = {}
    if subagents_dir.is_dir():
        # rglob (not glob): Sub-agent mode stores meta/transcripts flat, but
        # Workflow mode nests them under workflows/wf_<id>/. Resolve each
        # sidechain jsonl relative to its own meta's directory.
        for meta_file in sorted(subagents_dir.rglob("*.meta.json")):
            meta = json.loads(meta_file.read_text())
            tool_use_id = meta.get("toolUseId", "")
            # meta file: "agent-a0.meta.json" -> agent_id: "agent-a0".
            # Workflow meta carries no toolUseId, so no spawn link is recorded
            # here — the spawn tree is rebuilt from the workflow journal instead.
            sidechain_stem = meta_file.name.replace(".meta.json", "")
            if tool_use_id:
                tool_use_to_child[tool_use_id] = sidechain_stem

            sidechain_jsonl = meta_file.parent / f"{sidechain_stem}.jsonl"
            if sidechain_jsonl.exists():
                all_events.extend(parse_jsonl(sidechain_jsonl))

    # Phase 2: resolve child_agent_id against the complete event set.
    if tool_use_to_child:
        for i, event in enumerate(all_events):
            if event.type != EventType.AGENT_SPAWN:
                continue
            child = tool_use_to_child.get(event.data.get("tool_use_id", ""))
            if child:
                all_events[i] = UnifiedEvent.create(
                    timestamp=event.timestamp,
                    agent_id=event.agent_id,
                    source=event.source,
                    type=event.type,
                    data={**event.data, "child_agent_id": child},
                    parent_id=event.parent_id,
                )

    # Parse team-events if present
    team_events_file = raw_dir / "team-events.jsonl"
    if team_events_file.exists():
        all_events.extend(parse_team_events(team_events_file))

    # Sort by timestamp
    all_events.sort(key=lambda e: e.timestamp)

    return all_events


def load_team_config(raw_dir: Path) -> dict[str, Any] | None:
    """Load the collected team config.json (authoritative member/role list)."""
    config_file = raw_dir / "team-config.json"
    if not config_file.exists():
        return None
    try:
        data = json.loads(config_file.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def load_workflow_journals(raw_dir: Path) -> list[Mapping[str, object]]:
    """Load collected Workflow run journals (raw/workflows/wf_*.json).

    Each journal is authoritative topology ground truth for a Workflow-mode run
    — its `workflowProgress` lists every spawned agent with its phase, label,
    model and usage. Mirrors `load_team_config`. Returns [] when absent.
    """
    workflows_dir = raw_dir / "workflows"
    if not workflows_dir.is_dir():
        return []
    journals: list[Mapping[str, object]] = []
    for f in sorted(workflows_dir.glob("*.json")):
        try:
            data = json.loads(f.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            journals.append(cast(Mapping[str, object], data))
    return journals


def parse_team_events(path: Path) -> list[UnifiedEvent]:
    """Parse team-events.jsonl, diffing snapshots *per file path*.

    Snapshots of many mailboxes and task files are interleaved in one stream, so
    state must be tracked per path (not against the globally-previous snapshot,
    which could belong to a different file). Mailboxes yield message_send /
    message_read; task files yield task_create / task_update.
    """
    events: list[UnifiedEvent] = []
    last_mailbox: dict[str, list[dict[str, Any]]] = {}
    last_task: dict[str, tuple[str, str]] = {}  # path -> (status, owner)
    seen_task: set[str] = set()

    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            snap = json.loads(line)
            ts = datetime.fromisoformat(snap["timestamp"].replace("Z", "+00:00"))
            kind = snap.get("kind")
            spath = str(snap.get("path", ""))
            content = snap.get("content")

            if kind == "mailbox_snapshot" and isinstance(content, list):
                curr = cast(list[dict[str, Any]], content)
                owner = Path(spath).stem
                prev = last_mailbox.get(spath)
                if prev is None:
                    for msg in curr:
                        events.append(UnifiedEvent.create(
                            timestamp=ts,
                            agent_id=owner,
                            source=EventSource.TEAM_EVENTS,
                            type=EventType.MESSAGE_SEND,
                            data={
                                "from": msg.get("from", ""),
                                "to": owner,
                                "summary": msg.get("summary", ""),
                                "message_type": "message",
                            },
                        ))
                else:
                    _diff_mailbox(prev, curr, ts, spath, events)
                last_mailbox[spath] = curr

            elif kind == "task_snapshot" and isinstance(content, dict):
                _diff_task(
                    cast(dict[str, Any], content), ts, spath, events, last_task, seen_task
                )

    return events


def _diff_task(
    task: dict[str, Any],
    ts: datetime,
    path: str,
    events: list[UnifiedEvent],
    last_task: dict[str, tuple[str, str]],
    seen_task: set[str],
) -> None:
    """Turn a task file snapshot into create/update events on first sight or change."""
    tid = str(task.get("id", ""))
    if not tid:
        return
    status = str(task.get("status", ""))
    owner = str(task.get("owner", ""))
    actor = owner or "team"  # the watcher sees file state, not the author

    if path not in seen_task:
        seen_task.add(path)
        events.append(UnifiedEvent.create(
            timestamp=ts,
            agent_id=actor,
            source=EventSource.TEAM_EVENTS,
            type=EventType.TASK_CREATE,
            data={"task_id": tid, "tool_use_id": "", "subject": str(task.get("subject", "")),
                  "description": str(task.get("description", ""))},
        ))
        last_task[path] = ("pending", "")

    prev_status, prev_owner = last_task.get(path, ("pending", ""))
    if (status, owner) != (prev_status, prev_owner):
        events.append(UnifiedEvent.create(
            timestamp=ts,
            agent_id=actor,
            source=EventSource.TEAM_EVENTS,
            type=EventType.TASK_UPDATE,
            data={"task_id": tid, "tool_use_id": "", "new_status": status,
                  "old_status": prev_status, "owner": owner},
        ))
        last_task[path] = (status, owner)


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
