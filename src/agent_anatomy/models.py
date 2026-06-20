from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4


class EventSource(Enum):
    TRANSCRIPT = "transcript"
    TEAM_EVENTS = "team_events"


class EventType(Enum):
    AGENT_SPAWN = "agent_spawn"
    AGENT_COMPLETE = "agent_complete"
    MESSAGE_SEND = "message_send"
    MESSAGE_READ = "message_read"
    TASK_CREATE = "task_create"
    TASK_UPDATE = "task_update"
    AGENT_MESSAGE = "agent_message"


@dataclass(frozen=True)
class UnifiedEvent:
    event_id: UUID
    timestamp: datetime
    agent_id: str
    source: EventSource
    type: EventType
    data: dict[str, Any]
    parent_id: UUID | None = None

    @classmethod
    def create(
        cls,
        *,
        timestamp: datetime,
        agent_id: str,
        source: EventSource,
        type: EventType,
        data: dict[str, Any],
        parent_id: UUID | None = None,
    ) -> "UnifiedEvent":
        return cls(
            event_id=uuid4(),
            timestamp=timestamp,
            agent_id=agent_id,
            source=source,
            type=type,
            data=data,
            parent_id=parent_id,
        )
