from datetime import UTC, datetime

from agent_anatomy.comparator import (
    agent_output_markdown,
    build_agent_outputs,
    session_summary,
)
from agent_anatomy.models import EventSource, EventType, UnifiedEvent
from agent_anatomy.roles import build_topology


def test_session_summary_renders_team_mode_shared_task_board():
    events = [
        UnifiedEvent.create(
            timestamp=datetime(2026, 6, 18, 12, 0, 0, tzinfo=UTC),
            agent_id="team-lead@t1",
            source=EventSource.TRANSCRIPT,
            type=EventType.TASK_CREATE,
            data={"task_id": "1", "subject": "investigate bet 2"},
        ),
        UnifiedEvent.create(
            timestamp=datetime(2026, 6, 18, 12, 0, 1, tzinfo=UTC),
            agent_id="team-lead@t1",
            source=EventSource.TRANSCRIPT,
            type=EventType.MESSAGE_SEND,
            data={"from": "team-lead", "to": "Bet-2", "summary": "go", "message_type": "task_assignment"},
        ),
        UnifiedEvent.create(
            timestamp=datetime(2026, 6, 18, 12, 0, 5, tzinfo=UTC),
            agent_id="Bet-2",
            source=EventSource.TRANSCRIPT,
            type=EventType.TASK_UPDATE,
            data={"task_id": "1", "new_status": "in_progress", "owner": "Bet-2"},
        ),
    ]
    md = session_summary(events)
    assert "Agent Team mode" in md
    assert "Shared task board" in md
    assert "investigate bet 2" in md
    assert "owner: Bet-2" in md


def test_build_agent_outputs_collects_full_text():
    events = [
        UnifiedEvent.create(
            timestamp=datetime(2026, 6, 18, 12, 0, 5, tzinfo=UTC),
            agent_id="agent-x", source=EventSource.TRANSCRIPT, type=EventType.AGENT_MESSAGE,
            data={"role": "assistant", "content_summary": "short", "text": "the full long answer"},
        ),
        UnifiedEvent.create(
            timestamp=datetime(2026, 6, 18, 12, 0, 0, tzinfo=UTC),
            agent_id="agent-x", source=EventSource.TRANSCRIPT, type=EventType.AGENT_MESSAGE,
            data={"role": "user", "content_summary": "task", "text": "your instruction"},
        ),
    ]
    topo = build_topology(events)
    outputs = build_agent_outputs(events, topo)
    assert len(outputs) == 1
    o = outputs[0]
    # messages are time-ordered: the instruction (t=0) comes first
    assert o.messages[0][1] == "user"
    assert o.messages[0][2] == "your instruction"
    assert o.messages[1][2] == "the full long answer"

    md = agent_output_markdown(o)
    assert "your instruction" in md
    assert "the full long answer" in md


def test_build_agent_outputs_labels_meta_turns_as_injected():
    # A harness-injected (isMeta) turn reads as "user" but is relabelled so it
    # isn't confused with the parent's instruction or the agent's own output.
    events = [
        UnifiedEvent.create(
            timestamp=datetime(2026, 6, 18, 12, 0, 0, tzinfo=UTC),
            agent_id="agent-x", source=EventSource.TRANSCRIPT, type=EventType.AGENT_MESSAGE,
            data={"role": "user", "text": "Run the deep-research workflow.", "is_meta": True},
        ),
    ]
    outputs = build_agent_outputs(events, build_topology(events))
    assert outputs[0].messages[0][1] == "injected"


def test_session_summary_is_markdown():
    events = [
        UnifiedEvent.create(
            timestamp=datetime(2026, 6, 18, 12, 0, 0, tzinfo=UTC),
            agent_id="main",
            source=EventSource.TRANSCRIPT,
            type=EventType.AGENT_MESSAGE,
            data={"role": "user", "content_summary": "hello", "token_usage": {}, "tool_calls": []},
        ),
    ]
    md = session_summary(events)
    assert isinstance(md, str)
    assert "# " in md
