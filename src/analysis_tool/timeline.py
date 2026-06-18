from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from analysis_tool.models import UnifiedEvent


def build_timeline_data(events: list[UnifiedEvent]) -> dict[str, Any]:
    """Build JSON-serializable data for the D3.js timeline visualization."""
    agent_ids = sorted({e.agent_id for e in events})
    agents = [{"id": aid, "label": aid.split("@")[0] if "@" in aid else aid} for aid in agent_ids]
    agent_index = {aid: i for i, aid in enumerate(agent_ids)}

    if events:
        t0 = events[0].timestamp
        t1 = events[-1].timestamp
        total_seconds = max((t1 - t0).total_seconds(), 1)
    else:
        t0 = events[0].timestamp if events else None
        total_seconds = 1

    event_list: list[dict[str, Any]] = []
    for e in events:
        offset_seconds = (e.timestamp - t0).total_seconds() if t0 else 0
        event_list.append({
            "event_id": str(e.event_id),
            "agent_id": e.agent_id,
            "agent_row": agent_index.get(e.agent_id, 0),
            "type": e.type.value,
            "timestamp": e.timestamp.isoformat(),
            "offset_seconds": offset_seconds,
            "offset_pct": (offset_seconds / total_seconds) * 100,
            "parent_id": str(e.parent_id) if e.parent_id else None,
            "data_summary": _summarize_data(e),
        })

    return {
        "agents": agents,
        "events": event_list,
        "total_seconds": total_seconds,
        "event_count": len(events),
    }


def _summarize_data(event: UnifiedEvent) -> str:
    """Produce a short human-readable summary of event data."""
    t = event.type.value
    if t == "agent_spawn":
        return f"spawn -> {event.data.get('child_agent_id', '?')}"
    if t == "message_send":
        return f"{event.data.get('from', '?')} -> {event.data.get('to', '?')}: {event.data.get('summary', '')}"
    if t == "task_create":
        return f"task: {event.data.get('subject', '?')}"
    if t == "task_update":
        return f"-> {event.data.get('new_status', '?')}"
    if t == "agent_message":
        return event.data.get("content_summary", "")[:100]
    return ""


def render_html(data: dict[str, Any], template_dir: Path, output_path: Path) -> None:
    """Render timeline data into an HTML file using the Jinja2 template."""
    env = Environment(loader=FileSystemLoader(str(template_dir)))
    template = env.get_template("timeline.html.j2")
    html = template.render(**data)
    output_path.write_text(html)
