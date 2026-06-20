from datetime import UTC, datetime

from agent_anatomy.models import EventSource, EventType, UnifiedEvent
from agent_anatomy.state_machine import (
    build_state_machines,
    detect_anomalies,
)


def make_event(**kwargs: object) -> UnifiedEvent:
    defaults: dict[str, object] = {
        "timestamp": datetime(2026, 6, 18, 12, 0, 0, tzinfo=UTC),
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
            timestamp=datetime(2026, 6, 18, 12, 1, 0, tzinfo=UTC),
            data={"task_id": "t1", "new_status": "in_progress", "old_status": "", "owner": "agent-1"},
        ),
        make_event(
            type=EventType.TASK_UPDATE,
            timestamp=datetime(2026, 6, 18, 12, 2, 0, tzinfo=UTC),
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
            timestamp=datetime(2026, 6, 18, 12, 1, 0, tzinfo=UTC),
            data={"task_id": "t1", "new_status": "in_progress", "old_status": "", "owner": "agent-1"},
        ),
    ]
    machines = build_state_machines(events)
    anomalies = detect_anomalies(machines)
    assert any(a.kind == "stuck_in_progress" for a in anomalies)
