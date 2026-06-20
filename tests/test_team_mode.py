"""Agent-team end-to-end: collected team data must drive the analysis."""
import json
from datetime import UTC, datetime
from pathlib import Path

from agent_anatomy.comparator import build_session_view, session_summary
from agent_anatomy.parser import load_team_config, parse_raw_dir, parse_team_events
from agent_anatomy.roles import AgentRole, SessionMode


def test_team_fixture_end_to_end(fixtures_dir: Path):
    raw = fixtures_dir / "team" / "raw"
    events = parse_raw_dir(raw)
    config = load_team_config(raw)
    assert config is not None  # team-config.json is loaded

    view = build_session_view(events, config)
    topo = view.topology

    # mode + authoritative roles from config.json
    assert topo.mode == SessionMode.AGENT_TEAM
    assert topo.profiles["team-lead@team1"].role == AgentRole.LEAD
    assert topo.profiles["Mate"].role == AgentRole.TEAMMATE

    # the shared task board reflects the claim + completion seen in team-events
    assert len(view.tasks) == 1
    task = view.tasks[0]
    assert task.task_id == "1"
    assert task.owner == "Mate"
    assert task.final_status == "completed"
    assert view.private_todos == []  # nothing private in team mode
    assert view.anomalies == []  # has a create and reached completed

    md = session_summary(events, view)
    assert "Agent Team mode" in md
    assert "Shared task board" in md


def test_taskcreate_id_backfilled_from_result_text(fixtures_dir: Path):
    # The TaskCreate result is plain text "Task #1 created…" — id must be recovered.
    events = parse_raw_dir(fixtures_dir / "team" / "raw")
    creates = [e for e in events if e.type.value == "task_create"]
    assert creates and any(e.data.get("task_id") == "1" for e in creates)


def _snap(ts: str, path: str, kind: str, content: object) -> str:
    return json.dumps({"timestamp": ts, "path": path, "kind": kind, "content": content})


def test_parse_team_events_task_snapshots(tmp_path: Path):
    p = "/x/tasks/t/1.json"
    lines = [
        _snap("2026-06-18T12:00:00.000Z", p, "task_snapshot",
              {"id": "1", "subject": "do it", "status": "pending", "owner": ""}),
        _snap("2026-06-18T12:00:05.000Z", p, "task_snapshot",
              {"id": "1", "subject": "do it", "status": "in_progress", "owner": "Mate"}),
        _snap("2026-06-18T12:00:09.000Z", p, "task_snapshot",
              {"id": "1", "subject": "do it", "status": "completed", "owner": "Mate"}),
    ]
    f = tmp_path / "team-events.jsonl"
    f.write_text("\n".join(lines) + "\n")

    events = parse_team_events(f)
    kinds = [e.type.value for e in events]
    assert kinds.count("task_create") == 1
    updates = [e for e in events if e.type.value == "task_update"]
    statuses = [u.data.get("new_status") for u in updates]
    assert "in_progress" in statuses and "completed" in statuses
    assert any(u.data.get("owner") == "Mate" for u in updates)


def test_parse_team_events_diffs_mailboxes_per_path(tmp_path: Path):
    # Two different mailboxes interleaved must not be diffed against each other.
    lines = [
        _snap("2026-06-18T12:00:00.000Z", "/x/inboxes/A.json", "mailbox_snapshot",
              [{"from": "lead", "summary": "hi A"}]),
        _snap("2026-06-18T12:00:01.000Z", "/x/inboxes/B.json", "mailbox_snapshot",
              [{"from": "lead", "summary": "hi B"}]),
        _snap("2026-06-18T12:00:02.000Z", "/x/inboxes/A.json", "mailbox_snapshot",
              [{"from": "lead", "summary": "hi A"}, {"from": "lead", "summary": "second to A"}]),
    ]
    f = tmp_path / "team-events.jsonl"
    f.write_text("\n".join(lines) + "\n")
    sends = [e for e in parse_team_events(f) if e.type.value == "message_send"]
    summaries = {e.data.get("summary") for e in sends}
    assert {"hi A", "hi B", "second to A"} <= summaries


def test_build_topology_team_config_only(tmp_path: Path):
    # config presence alone should classify roles even with no message evidence.
    from agent_anatomy.models import EventSource, EventType, UnifiedEvent
    from agent_anatomy.roles import build_topology

    events = [
        UnifiedEvent.create(
            timestamp=datetime(2026, 6, 18, 12, 0, 0, tzinfo=UTC),
            agent_id="Mate",
            source=EventSource.TRANSCRIPT,
            type=EventType.AGENT_MESSAGE,
            data={"role": "assistant", "content_summary": "working", "text": "working"},
        ),
    ]
    config = {
        "leadAgentId": "team-lead@t",
        "members": [
            {"agentId": "team-lead@t", "name": "team-lead", "agentType": "team-lead"},
            {"agentId": "Mate", "name": "Mate", "agentType": "general-purpose"},
        ],
    }
    topo = build_topology(events, config)
    assert topo.mode == SessionMode.AGENT_TEAM
    assert topo.profiles["Mate"].role == AgentRole.TEAMMATE
