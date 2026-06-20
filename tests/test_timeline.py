from datetime import UTC, datetime

from agent_anatomy.models import EventSource, EventType, UnifiedEvent
from agent_anatomy.timeline import build_timeline_data


def test_build_timeline_data_groups_by_agent():
    events = [
        UnifiedEvent.create(
            timestamp=datetime(2026, 6, 18, 12, 0, 0, tzinfo=UTC),
            agent_id="main",
            source=EventSource.TRANSCRIPT,
            type=EventType.AGENT_SPAWN,
            data={"child_agent_id": "a0", "tool_use_id": "c1"},
        ),
        UnifiedEvent.create(
            timestamp=datetime(2026, 6, 18, 12, 0, 30, tzinfo=UTC),
            agent_id="a0",
            source=EventSource.TRANSCRIPT,
            type=EventType.AGENT_MESSAGE,
            data={"role": "assistant", "content_summary": "hello", "token_usage": {}, "tool_calls": []},
        ),
    ]

    data = build_timeline_data(events)

    assert "agents" in data
    assert len(data["agents"]) == 2
    assert "events" in data
    assert len(data["events"]) == 2

    agent_ids = [a["id"] for a in data["agents"]]
    assert "main" in agent_ids
    assert "a0" in agent_ids
