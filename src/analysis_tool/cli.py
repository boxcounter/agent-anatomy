import json
import signal
import threading
from pathlib import Path

import click
from jinja2 import TemplateNotFound

from analysis_tool.collect import collect_session, find_session_dir
from analysis_tool.errors import (
    AnalysisToolError,
    RawDataNotFoundError,
    SessionNotFoundError,
    TemplateNotFoundError,
    WatchTargetNotFoundError,
)
from analysis_tool.models import UnifiedEvent
from analysis_tool.parser import parse_raw_dir


def _debug() -> bool:
    """Check if --debug flag was passed."""
    ctx = click.get_current_context()
    # ctx.ensure_object(dict) was called in main(), so obj is always a dict
    obj: dict[object, object] = ctx.obj  # type: ignore[assignment]
    return bool(obj.get("debug", False))


@click.group()
@click.option("--debug", is_flag=True, default=False, help="Show full tracebacks on error")
@click.pass_context
def main(ctx: click.Context, debug: bool) -> None:  # type: ignore[no-any-unimported]
    """Claude Code Agent Team session analysis tool."""
    ctx.ensure_object(dict)
    ctx.obj["debug"] = debug


@main.command()
@click.option("--session-id", required=True, help="Session ID to collect")
@click.option(
    "--output",
    "-o",
    "output_dir",
    default=None,
    help="Output directory (default: ./analysis)",
)
def collect(session_id: str, output_dir: str | None) -> None:
    """Collect raw data from a Sub-agent mode session."""
    try:
        _collect(session_id, output_dir)
    except SessionNotFoundError as exc:
        click.echo(
            f"Session '{exc.session_id}' not found.\n\n"
            f"  Look up session IDs with: ls ~/.claude/projects/*/",
            err=True,
        )
        if _debug():
            raise
        raise SystemExit(1)
    except RawDataNotFoundError as exc:
        click.echo(
            f"No session data at {exc.path}.\n\n"
            f"  Run 'collect --session-id=<id>' first to gather raw data,\n"
            f"  or check that the path points to a directory containing raw/session.jsonl.",
            err=True,
        )
        if _debug():
            raise
        raise SystemExit(1)
    except AnalysisToolError as exc:
        click.echo(str(exc), err=True)
        if _debug():
            raise
        raise SystemExit(1)
    except OSError as exc:
        click.echo(f"File system error: {exc.strerror or exc}", err=True)
        if _debug():
            raise
        raise SystemExit(1)


def _collect(session_id: str, output_dir: str | None) -> None:
    output_path = Path(output_dir) if output_dir else Path.cwd()

    analysis_dir = collect_session(session_id, output_path)
    click.echo(f"Raw data collected to {analysis_dir / 'raw'}")

    events = parse_raw_dir(analysis_dir / "raw")
    events_file = analysis_dir / "events.jsonl"

    with open(events_file, "w") as f:
        for event in events:
            f.write(json.dumps(_event_to_dict(event), default=str) + "\n")
    click.echo(f"Parsed {len(events)} events to {events_file}")


@main.command()
@click.option("--session-id", default=None, help="Session ID (auto-resolves analysis dir from ~/.claude/projects)")
@click.option("--session-dir", default=None, help="Path to analysis/ directory")
def analyze(session_id: str | None, session_dir: str | None) -> None:
    """Analyze a collected session and generate reports.

    Use --session-id for convenience (auto-finds the session).
    Use --session-dir when you collected data to a custom location.
    """
    if session_id and session_dir:
        click.echo("Error: use --session-id or --session-dir, not both.", err=True)
        raise SystemExit(1)

    try:
        if session_id:
            resolved = str(find_session_dir(session_id) / "analysis")
        elif session_dir:
            resolved = session_dir
        else:
            resolved = "analysis"  # default: ./analysis
        _analyze(resolved)
    except SessionNotFoundError as exc:
        click.echo(
            f"Session '{exc.session_id}' not found.\n\n"
            f"  Look up session IDs with: ls ~/.claude/projects/*/",
            err=True,
        )
        if _debug():
            raise
        raise SystemExit(1)
    except RawDataNotFoundError as exc:
        click.echo(
            f"No session data at {exc.path}.\n\n"
            f"  Run 'collect --session-id=<id>' first to gather raw data,\n"
            f"  or check that the path points to a directory containing raw/session.jsonl.",
            err=True,
        )
        if _debug():
            raise
        raise SystemExit(1)
    except TemplateNotFoundError as exc:
        click.echo(
            f"Template '{exc.template_name}' is missing.\n\n"
            f"  Reinstall the package: uv sync",
            err=True,
        )
        if _debug():
            raise
        raise SystemExit(1)
    except AnalysisToolError as exc:
        click.echo(str(exc), err=True)
        if _debug():
            raise
        raise SystemExit(1)
    except OSError as exc:
        click.echo(f"File system error: {exc.strerror or exc}", err=True)
        if _debug():
            raise
        raise SystemExit(1)


def _analyze(session_dir: str) -> None:
    analysis_dir = Path(session_dir)
    raw_dir = analysis_dir / "raw"

    if not raw_dir.is_dir():
        click.echo(f"Error: raw/ directory not found in {analysis_dir}", err=True)
        raise SystemExit(1)

    events = parse_raw_dir(raw_dir)
    click.echo(f"Parsed {len(events)} events")

    events_file = analysis_dir / "events.jsonl"
    with open(events_file, "w") as f:
        for event in events:
            f.write(json.dumps(_event_to_dict(event), default=str) + "\n")

    # Keystone: one topology drives every artifact, so they never disagree.
    from analysis_tool.comparator import (
        agent_output_markdown,
        build_agent_outputs,
        build_session_view,
        outputs_to_dicts,
        session_summary,
        view_to_dict,
    )
    from analysis_tool.parser import load_team_config, load_workflow_journals
    team_config = load_team_config(raw_dir)  # authoritative roles, when present
    workflow_journals = load_workflow_journals(raw_dir)  # authoritative for Workflow mode
    view = build_session_view(events, team_config, workflow_journals)
    topology = view.topology

    click.echo(f"\nMode: {topology.mode.value}")
    role_counts: dict[str, int] = {}
    for p in topology.profiles.values():
        role_counts[p.role.value] = role_counts.get(p.role.value, 0) + 1
    click.echo("  Roles: " + ", ".join(f"{n} {r}" for r, n in sorted(role_counts.items())))

    click.echo(f"\nShared task board: {len(view.tasks)} team tasks")
    for t in view.tasks:
        path_str = " -> ".join(tr[0] for tr in t.transitions)
        owner = f" [{t.owner}]" if t.owner else ""
        click.echo(f"  #{t.task_id}{owner}: {path_str}")
    if view.private_todos:
        total = sum(g.total for g in view.private_todos)
        click.echo(f"Private to-do lists: {total} todos across {len(view.private_todos)} agents")
    if view.anomalies:
        click.echo(f"\nAnomalies ({len(view.anomalies)}):")
        for detail in view.anomalies:
            click.echo(f"  {detail}")

    from analysis_tool.graph import build_collaboration_graph, to_force_data, to_mermaid
    graph = build_collaboration_graph(events)
    mermaid = to_mermaid(graph, topology)
    graph_file = analysis_dir / "graph.mermaid"
    graph_file.write_text(mermaid)
    click.echo(f"\nCollaboration graph written to {graph_file}")

    report_file = analysis_dir / "report.md"
    report_file.write_text(session_summary(events, view))  # reuse the prebuilt view
    click.echo(f"Report (markdown) written to {report_file}")

    # Per-agent full outputs (untruncated), one Markdown file each.
    outputs = build_agent_outputs(events, topology)
    agents_dir = analysis_dir / "agents"
    agents_dir.mkdir(exist_ok=True)
    for o in outputs:
        fname = f"{o.agent_id}-{_slug(o.label)}.md"  # full id avoids prefix collisions
        (agents_dir / fname).write_text(agent_output_markdown(o))
    click.echo(f"Full agent outputs written to {agents_dir}/ ({len(outputs)} files)")

    from analysis_tool.timeline import build_timeline_data, render_html, render_template
    template_dir = Path(__file__).parent / "templates"
    timeline_data = build_timeline_data(events, topology)
    timeline_file = analysis_dir / "timeline.html"
    report_html_file = analysis_dir / "report.html"
    try:
        render_html(timeline_data, template_dir, timeline_file)
        click.echo(f"Timeline written to {timeline_file}")
        render_template(
            {
                "view": view_to_dict(view),
                "graph": to_force_data(graph, topology),
                "timeline": timeline_data,
                "outputs": outputs_to_dicts(outputs),
            },
            template_dir,
            "report.html.j2",
            report_html_file,
        )
        click.echo(f"Explainer (HTML) written to {report_html_file}")
    except TemplateNotFound as exc:
        name: str = exc.name if isinstance(exc.name, str) else str(exc)
        raise TemplateNotFoundError(name) from exc

    click.echo("\nDone.")


@main.command()
@click.option("--team-name", required=True, help="Team name (same as session ID)")
@click.option("--output", "-o", "output_dir", default=None, help="Output directory (default: ./analysis)")
def watch(team_name: str, output_dir: str | None) -> None:
    """Monitor Agent Team communication files in real-time.

    Runs until interrupted (Ctrl+C). Outputs team-events.jsonl.
    """
    try:
        _watch(team_name, output_dir)
    except WatchTargetNotFoundError as exc:
        click.echo(
            f"Team '{exc.team_name}' not found.\n\n"
            f"  Make sure an Agent Team session with this name is active.\n"
            f"  Team directories: ls ~/.claude/teams/",
            err=True,
        )
        if _debug():
            raise
        raise SystemExit(1)
    except AnalysisToolError as exc:
        click.echo(str(exc), err=True)
        if _debug():
            raise
        raise SystemExit(1)
    except OSError as exc:
        click.echo(f"File system error: {exc.strerror or exc}", err=True)
        if _debug():
            raise
        raise SystemExit(1)


def _watch(team_name: str, output_dir: str | None) -> None:
    from analysis_tool.watch import watch_teams

    output_path = Path(output_dir) if output_dir else Path("analysis")

    teams_dir = Path.home() / ".claude" / "teams" / team_name
    if not teams_dir.is_dir():
        raise WatchTargetNotFoundError(team_name)

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


def _slug(text: str) -> str:
    """Filesystem-safe slug for per-agent output filenames."""
    cleaned = "".join(c if c.isalnum() else "-" for c in text).strip("-")
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return (cleaned[:50] or "agent").lower()


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
