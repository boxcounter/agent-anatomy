"""Smoke tests for the HTML artifacts.

The Jinja templates carry real logic now (phase-folded cast, Phases table,
StructuredOutput drawers). These render the actual code path end to end and
assert the templates don't throw and contain their key fragments.
"""
from pathlib import Path

import agent_anatomy
from agent_anatomy.comparator import (
    build_agent_outputs,
    build_session_view,
    outputs_to_dicts,
    view_to_dict,
)
from agent_anatomy.graph import build_collaboration_graph, to_force_data
from agent_anatomy.parser import load_workflow_journals, parse_raw_dir
from agent_anatomy.timeline import build_timeline_data, render_html, render_template

TEMPLATES = Path(agent_anatomy.__file__).parent / "templates"


def _render_report(raw: Path, tmp_path: Path) -> str:
    events = parse_raw_dir(raw)
    wf = load_workflow_journals(raw)
    view = build_session_view(events, None, wf)
    topo = view.topology
    graph = build_collaboration_graph(events)
    outputs = build_agent_outputs(events, topo)
    timeline_data = build_timeline_data(events, topo)

    # Timeline template must render without error too.
    render_html(timeline_data, TEMPLATES, tmp_path / "timeline.html")

    out = tmp_path / "report.html"
    render_template(
        {
            "view": view_to_dict(view),
            "graph": to_force_data(graph, topo),
            "timeline": timeline_data,
            "outputs": outputs_to_dicts(outputs),
        },
        TEMPLATES,
        "report.html.j2",
        out,
    )
    return out.read_text()


def test_workflow_report_renders_phases_and_folded_cast(fixtures_dir: Path, tmp_path: Path):
    html = _render_report(fixtures_dir / "workflow" / "raw", tmp_path)
    assert "Phases" in html
    assert 'class="phase-group"' in html  # cast folded into per-phase <details>
    assert "[Search]" in html  # agent display name carries its phase


def test_subagent_report_renders_flat_cast(fixtures_dir: Path, tmp_path: Path):
    # Non-workflow mode: flat cast table, no phase-group folding.
    html = _render_report(fixtures_dir, tmp_path)
    assert "Cast — who is who" in html
    assert 'class="phase-group"' not in html
