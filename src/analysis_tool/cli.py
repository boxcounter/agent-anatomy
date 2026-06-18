import json
import signal
import threading
from pathlib import Path

import click

from analysis_tool.collect import collect_session, find_session_dir
from analysis_tool.models import UnifiedEvent
from analysis_tool.parser import parse_raw_dir


@click.group()
def main() -> None:
    """Claude Code Agent Team session analysis tool."""
    pass


@main.command()
@click.option("--session-id", required=True, help="Session ID to collect")
@click.option(
    "--output",
    "output_dir",
    default=None,
    help="Output directory (default: next to session dir)",
)
def collect(session_id: str, output_dir: str | None) -> None:
    """Collect raw data from a Sub-agent mode session."""
    if output_dir is None:
        output_path = find_session_dir(session_id)
    else:
        output_path = Path(output_dir)

    analysis_dir = collect_session(session_id, output_path)
    click.echo(f"Raw data collected to {analysis_dir / 'raw'}")

    # Also run parser immediately
    events = parse_raw_dir(analysis_dir / "raw")
    events_file = analysis_dir / "events.jsonl"

    with open(events_file, "w") as f:
        for event in events:
            f.write(json.dumps(_event_to_dict(event), default=str) + "\n")
    click.echo(f"Parsed {len(events)} events to {events_file}")


@main.command()
@click.option("--session-dir", required=True, help="Path to analysis/ directory")
def analyze(session_dir: str) -> None:
    """Analyze a collected session and generate reports."""
    import json

    analysis_dir = Path(session_dir)
    raw_dir = analysis_dir / "raw"

    if not raw_dir.is_dir():
        click.echo(f"Error: raw/ directory not found in {analysis_dir}", err=True)
        raise SystemExit(1)

    # Parse events
    events = parse_raw_dir(raw_dir)
    click.echo(f"Parsed {len(events)} events")

    # Write unified event stream
    events_file = analysis_dir / "events.jsonl"
    with open(events_file, "w") as f:
        for event in events:
            f.write(json.dumps(_event_to_dict(event), default=str) + "\n")

    # Generate state machine report
    from analysis_tool.state_machine import build_state_machines, detect_anomalies
    machines = build_state_machines(events)
    anomalies = detect_anomalies(machines)

    click.echo(f"\nTask State Machines: {len(machines)} tasks")
    for task_id, transitions in machines.items():
        path_str = " -> ".join(t.status for t in transitions)
        click.echo(f"  {task_id}: {path_str}")

    if anomalies:
        click.echo(f"\nAnomalies ({len(anomalies)}):")
        for a in anomalies:
            click.echo(f"  [{a.kind}] {a.detail}")

    # Generate collaboration graph
    from analysis_tool.graph import build_collaboration_graph, to_mermaid
    graph = build_collaboration_graph(events)
    mermaid = to_mermaid(graph)

    graph_file = analysis_dir / "graph.mermaid"
    graph_file.write_text(mermaid)
    click.echo(f"\nCollaboration graph written to {graph_file}")
    click.echo(f"  Nodes: {len(graph.nodes)}, Edges: {len(graph.edges)}")

    # Generate report
    from analysis_tool.comparator import session_summary
    summary = session_summary(events)
    report_file = analysis_dir / "report.md"
    report_file.write_text(summary)
    click.echo(f"\nReport written to {report_file}")

    # Generate timeline
    from analysis_tool.timeline import build_timeline_data, render_html
    timeline_data = build_timeline_data(events)
    template_dir = Path(__file__).parent / "templates"
    timeline_file = analysis_dir / "timeline.html"
    render_html(timeline_data, template_dir, timeline_file)
    click.echo(f"Timeline written to {timeline_file}")

    click.echo("\nDone.")


@main.command()
@click.option("--team-name", required=True, help="Team name (same as session ID)")
@click.option("--output", "output_dir", default=None, help="Output directory for analysis data")
def watch(team_name: str, output_dir: str | None) -> None:
    """Monitor Agent Team communication files in real-time.

    Runs until interrupted (Ctrl+C). Outputs team-events.jsonl.
    """
    from pathlib import Path

    from analysis_tool.watch import watch_teams

    if output_dir is None:
        output_path = Path.home() / ".claude" / "agent-team-analysis" / team_name
    else:
        output_path = Path(output_dir)

    stop_event = threading.Event()

    def _handle_signal(signum: int, frame: object) -> None:
        click.echo("\nStopping watcher...")
        stop_event.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    click.echo(f"Watching team '{team_name}'... (Ctrl+C to stop)")
    click.echo(f"Output: {output_path / 'raw' / 'team-events.jsonl'}")

    watch_teams(team_name, output_path, stop_event)

    click.echo(f"Done. Events written to {output_path / 'raw' / 'team-events.jsonl'}")


def _event_to_dict(event: UnifiedEvent) -> dict[str, object]:
    """Serialize UnifiedEvent to a JSON-safe dict."""
    return {
        "event_id": str(event.event_id),
        "timestamp": event.timestamp.isoformat(),
        "agent_id": event.agent_id,
        "source": event.source.value,
        "type": event.type.value,
        "parent_id": str(event.parent_id) if event.parent_id else None,
        "data": event.data,
    }
