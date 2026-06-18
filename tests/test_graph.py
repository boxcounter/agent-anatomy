from datetime import UTC, datetime

from analysis_tool.graph import build_collaboration_graph, to_mermaid
from analysis_tool.models import EventSource, EventType, UnifiedEvent


def make_msg_event(from_agent: str, to_agent: str, ts_offset: int = 0) -> UnifiedEvent:
    return UnifiedEvent.create(
        timestamp=datetime(2026, 6, 18, 12, 0, ts_offset, tzinfo=UTC),
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

    assert "graph TD" in mmd
    assert "lead" in mmd
    assert "agent-a" in mmd
    assert "-->" in mmd
    assert "1 msg" in mmd
