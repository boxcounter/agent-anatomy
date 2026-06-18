import json
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
