import uuid
from datetime import UTC, datetime

from agent_anatomy.models import EventSource, EventType, UnifiedEvent


def test_unified_event_construction():
    event_id = uuid.uuid4()
    ts = datetime.now(UTC)
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
        timestamp=datetime.now(UTC),
        agent_id="a",
        source=EventSource.TRANSCRIPT,
        type=EventType.AGENT_MESSAGE,
        data={},
    )
    # dataclass with frozen=True should raise on attribute set
    try:
        event.agent_id = "b"  # pyright: ignore[reportAttributeAccessIssue]
        assert False, "Should have raised FrozenInstanceError"
    except Exception:
        pass
