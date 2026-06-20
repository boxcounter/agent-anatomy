from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from agent_anatomy.models import EventType, UnifiedEvent
from agent_anatomy.roles import AgentRole, Topology, build_topology, canonical_id

_ROLE_ORDER = {
    AgentRole.LEAD: 0,
    AgentRole.ROOT: 1,
    AgentRole.PHASE: 2,
    AgentRole.TEAMMATE: 3,
    AgentRole.SUBAGENT: 4,
    AgentRole.UNKNOWN: 5,
}


def build_timeline_data(events: list[UnifiedEvent], topology: Topology | None = None) -> dict[str, Any]:
    """Build JSON-serializable data for the D3 timeline.

    The x-axis is **event order**, not wall-clock: each event gets an evenly
    spaced position by its global sequence index, so long idle gaps don't crush
    the busy region into a sliver. Each agent is drawn as a single **activity
    bar** spanning its first→last event (role-coloured), with event ticks on it.
    Real wall-clock time is preserved for tooltips and a handful of axis anchors,
    so the compression doesn't lose timing information entirely.
    """
    if topology is None:
        topology = build_topology(events)

    # Synthetic phase nodes have no events of their own, so they'd render as
    # zero-width bars — exclude them from the lanes (their agents carry the story).
    ordered = sorted(
        (p for p in topology.profiles.values() if p.role != AgentRole.PHASE),
        key=lambda p: (_ROLE_ORDER.get(p.role, 9), p.first_seen.timestamp() if p.first_seen else 0.0),
    )
    agent_row = {p.agent_id: i for i, p in enumerate(ordered)}

    ordered_events = sorted(events, key=lambda e: e.timestamp)
    n = len(ordered_events)
    denom = max(n - 1, 1)
    t0 = ordered_events[0].timestamp if ordered_events else None

    def offset(ts: Any) -> float:
        return (ts - t0).total_seconds() if t0 else 0.0

    # Per-agent activity span (in event-sequence space) + real time bounds.
    agg: dict[str, dict[str, float]] = {}
    event_list: list[dict[str, Any]] = []
    for i, e in enumerate(ordered_events):
        cid = canonical_id(e.agent_id)
        seq_pct = (i / denom) * 100
        off = offset(e.timestamp)
        event_list.append({
            "agent_row": agent_row.get(cid, 0),
            "type": e.type.value,
            "seq_pct": seq_pct,
            "offset_seconds": off,
            "data_summary": _summarize_data(e),
        })
        a = agg.setdefault(cid, {"first": seq_pct, "last": seq_pct,
                                 "first_off": off, "last_off": off, "count": 0})
        a["last"] = seq_pct
        a["last_off"] = off
        a["count"] += 1

    agents = [
        {
            "id": p.agent_id,
            "label": p.display_name,
            "role": p.role.value,
            "first_pct": agg.get(p.agent_id, {}).get("first", 0.0),
            "last_pct": agg.get(p.agent_id, {}).get("last", 0.0),
            "first_off": agg.get(p.agent_id, {}).get("first_off", 0.0),
            "last_off": agg.get(p.agent_id, {}).get("last_off", 0.0),
            "count": int(agg.get(p.agent_id, {}).get("count", 0)),
        }
        for p in ordered
    ]

    # Spawn links: parent's spawn event → where the child first appears.
    spawn_links: list[dict[str, Any]] = []
    for i, e in enumerate(ordered_events):
        if e.type != EventType.AGENT_SPAWN:
            continue
        child = canonical_id(str(e.data.get("child_agent_id", "")))
        if not child or child not in agent_row:
            continue
        spawn_links.append({
            "parent_row": agent_row.get(canonical_id(e.agent_id), 0),
            "parent_pct": (i / denom) * 100,
            "child_row": agent_row[child],
            "child_pct": agg.get(child, {}).get("first", (i / denom) * 100),
        })

    # Real-time anchors: sample the elapsed time at evenly spaced event positions
    # so the event-order axis still carries a sense of when things happened.
    anchors: list[dict[str, Any]] = []
    if ordered_events:
        for frac in (0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100):
            idx = round((frac / 100) * denom)
            anchors.append({"pct": frac, "label": _fmt_secs(offset(ordered_events[idx].timestamp))})

    return {
        "agents": agents,
        "events": event_list,
        "spawn_links": spawn_links,
        "time_anchors": anchors,
        "event_count": len(events),
        "mode": topology.mode.value,
    }


def _fmt_secs(seconds: float) -> str:
    """Compact human time, e.g. 1617 -> '27m', 7325 -> '2h2m', 45 -> '45s'."""
    s = round(seconds)
    h, m, sec = s // 3600, (s % 3600) // 60, s % 60
    if h:
        return f"{h}h{m}m"
    if m:
        return f"{m}m"
    return f"{sec}s"


def _summarize_data(event: UnifiedEvent) -> str:
    """Produce a short human-readable summary of event data."""
    t = event.type.value
    if t == "agent_spawn":
        atype = event.data.get("agent_type", "")
        desc = event.data.get("description", "")
        return f"spawn [{atype}] {desc}".strip()
    if t == "message_send":
        d = event.data
        return (
            f"{d.get('from', '?')} → {d.get('to', '?')} "
            f"[{d.get('message_type', 'message')}]: {d.get('summary', '')}"
        )
    if t == "task_create":
        return f"create task: {event.data.get('subject', '?')}"
    if t == "task_update":
        owner = event.data.get("owner", "")
        suffix = f" (owner: {owner})" if owner else ""
        return f"task → {event.data.get('new_status', '?')}{suffix}"
    if t == "message_read":
        return f"read message from {event.data.get('from_agent', '?')}"
    if t == "agent_message":
        return str(event.data.get("content_summary", ""))[:120]
    return ""


def render_template(
    context: dict[str, Any], template_dir: Path, template_name: str, output_path: Path
) -> None:
    """Render any Jinja2 template in template_dir to output_path."""
    from agent_anatomy.comparator import humantime

    env = Environment(loader=FileSystemLoader(str(template_dir)))
    env.filters["humantime"] = humantime  # seconds -> "12h 21m" in templates
    template = env.get_template(template_name)
    output_path.write_text(template.render(**context))


def render_html(data: dict[str, Any], template_dir: Path, output_path: Path) -> None:
    """Render timeline data into an HTML file using the Jinja2 template."""
    render_template(data, template_dir, "timeline.html.j2", output_path)
