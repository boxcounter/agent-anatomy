from datetime import UTC, datetime

from analysis_tool.comparator import ComparisonReport, compare, session_summary
from analysis_tool.models import EventSource, EventType, UnifiedEvent


def test_compare_returns_report():
    events_a = [
        UnifiedEvent.create(
            timestamp=datetime(2026, 6, 18, 12, 0, 0, tzinfo=UTC),
            agent_id="main",
            source=EventSource.TRANSCRIPT,
            type=EventType.AGENT_SPAWN,
            data={"child_agent_id": "a0", "tool_use_id": "c1"},
        ),
        UnifiedEvent.create(
            timestamp=datetime(2026, 6, 18, 12, 1, 0, tzinfo=UTC),
            agent_id="a0",
            source=EventSource.TRANSCRIPT,
            type=EventType.AGENT_COMPLETE,
            data={"tokens_used": 1000, "duration_ms": 50000},
        ),
    ]
    events_b = [
        UnifiedEvent.create(
            timestamp=datetime(2026, 6, 18, 12, 0, 0, tzinfo=UTC),
            agent_id="lead",
            source=EventSource.TRANSCRIPT,
            type=EventType.MESSAGE_SEND,
            data={"from": "lead", "to": "agent-a", "summary": "task", "message_type": "task_assignment"},
        ),
        UnifiedEvent.create(
            timestamp=datetime(2026, 6, 18, 12, 1, 0, tzinfo=UTC),
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
    assert report.agent_count_a == 2
    assert report.agent_count_b == 1
    assert report.message_count_a == 0
    assert report.message_count_b == 2


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
