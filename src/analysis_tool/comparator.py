from dataclasses import dataclass, field

from analysis_tool.models import EventType, UnifiedEvent


@dataclass
class ComparisonReport:
    mode_a: str
    mode_b: str
    agent_count_a: int = 0
    agent_count_b: int = 0
    message_count_a: int = 0
    message_count_b: int = 0
    spawn_count_a: int = 0
    spawn_count_b: int = 0
    total_tokens_a: int = 0
    total_tokens_b: int = 0
    duration_seconds_a: float = 0.0
    duration_seconds_b: float = 0.0
    sections: list[str] = field(default_factory=lambda: [])


def compare(
    events_a: list[UnifiedEvent],
    mode_a: str,
    events_b: list[UnifiedEvent],
    mode_b: str,
) -> ComparisonReport:
    """Compare two sessions and produce a structured report."""
    report = ComparisonReport(mode_a=mode_a, mode_b=mode_b)

    agents_a = {e.agent_id for e in events_a}
    agents_b = {e.agent_id for e in events_b}
    report.agent_count_a = len(agents_a)
    report.agent_count_b = len(agents_b)

    report.message_count_a = sum(1 for e in events_a if e.type == EventType.MESSAGE_SEND)
    report.message_count_b = sum(1 for e in events_b if e.type == EventType.MESSAGE_SEND)

    report.spawn_count_a = sum(1 for e in events_a if e.type == EventType.AGENT_SPAWN)
    report.spawn_count_b = sum(1 for e in events_b if e.type == EventType.AGENT_SPAWN)

    for events, attr in [(events_a, "total_tokens_a"), (events_b, "total_tokens_b")]:
        total: int = 0
        for e in events:
            if e.type == EventType.AGENT_COMPLETE:
                total += int(e.data.get("tokens_used", 0))
            elif e.type == EventType.AGENT_MESSAGE:
                usage: object = e.data.get("token_usage", {})
                if isinstance(usage, dict):
                    total += int(usage.get("input_tokens", 0)) + int(usage.get("output_tokens", 0))  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
        setattr(report, attr, total)

    if events_a:
        report.duration_seconds_a = (events_a[-1].timestamp - events_a[0].timestamp).total_seconds()
    if events_b:
        report.duration_seconds_b = (events_b[-1].timestamp - events_b[0].timestamp).total_seconds()

    return report


def session_summary(events: list[UnifiedEvent]) -> str:
    """Generate a Markdown summary of a single session."""
    agent_ids = sorted({e.agent_id for e in events})
    spawns = sum(1 for e in events if e.type == EventType.AGENT_SPAWN)
    msgs = sum(1 for e in events if e.type == EventType.MESSAGE_SEND)
    tasks = sum(1 for e in events if e.type == EventType.TASK_CREATE)

    lines = [
        "# Session Analysis Report",
        "",
        f"**Agents**: {len(agent_ids)} ({', '.join(agent_ids[:10])})",
        f"**Agent spawns**: {spawns}",
        f"**Messages sent**: {msgs}",
        f"**Tasks created**: {tasks}",
        f"**Total events**: {len(events)}",
        "",
    ]

    if events:
        duration = (events[-1].timestamp - events[0].timestamp).total_seconds()
        lines.append(f"**Duration**: {duration:.1f}s")
        lines.append(f"**Time range**: {events[0].timestamp.isoformat()} -> {events[-1].timestamp.isoformat()}")

    return "\n".join(lines) + "\n"
