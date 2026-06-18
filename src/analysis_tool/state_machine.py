from dataclasses import dataclass
from datetime import datetime

from analysis_tool.models import EventType, UnifiedEvent


@dataclass
class StateTransition:
    task_id: str
    status: str
    agent_id: str
    timestamp: datetime


@dataclass
class Anomaly:
    task_id: str
    kind: str  # "orphan_update", "stuck_in_progress", "missing_dependency"
    detail: str


def build_state_machines(events: list[UnifiedEvent]) -> dict[str, list[StateTransition]]:
    """Reconstruct task state machines from create/update events."""
    machines: dict[str, list[StateTransition]] = {}

    task_events = [
        e for e in events
        if e.type in (EventType.TASK_CREATE, EventType.TASK_UPDATE)
    ]
    task_events.sort(key=lambda e: e.timestamp)

    for event in task_events:
        task_id = event.data.get("task_id", "")
        if not task_id:
            continue

        if task_id not in machines:
            machines[task_id] = []

        if event.type == EventType.TASK_CREATE:
            machines[task_id].append(StateTransition(
                task_id=task_id,
                status="pending",
                agent_id=event.agent_id,
                timestamp=event.timestamp,
            ))
        elif event.type == EventType.TASK_UPDATE:
            new_status = event.data.get("new_status", "")
            machines[task_id].append(StateTransition(
                task_id=task_id,
                status=new_status,
                agent_id=event.agent_id,
                timestamp=event.timestamp,
            ))

    return machines


def detect_anomalies(machines: dict[str, list[StateTransition]]) -> list[Anomaly]:
    """Detect anomalies in task state machines."""
    anomalies: list[Anomaly] = []

    for task_id, transitions in machines.items():
        has_create = any(t.status == "pending" for t in transitions)
        if not has_create:
            anomalies.append(Anomaly(
                task_id=task_id,
                kind="orphan_update",
                detail=f"Task {task_id} has updates but no create event",
            ))

        final_status = transitions[-1].status if transitions else "unknown"
        if final_status == "in_progress":
            anomalies.append(Anomaly(
                task_id=task_id,
                kind="stuck_in_progress",
                detail=f"Task {task_id} ended in in_progress without completion",
            ))

    return anomalies
