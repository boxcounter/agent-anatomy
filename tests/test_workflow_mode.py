"""Workflow-mode end-to-end: the run journal must drive the analysis.

A Workflow run nests its sub-agent transcripts under
subagents/workflows/wf_<id>/ and records the authoritative topology in
workflows/wf_<id>.json. The parser must find the nested agents, and the journal
must rebuild the orchestrator → phase → agent tree.
"""
import json
import shutil
from pathlib import Path

import pytest

from analysis_tool.collect import collect_session
from analysis_tool.comparator import build_session_view, session_summary
from analysis_tool.parser import load_workflow_journals, parse_raw_dir
from analysis_tool.roles import AgentRole, SessionMode


def _raw(fixtures_dir: Path) -> Path:
    return fixtures_dir / "workflow" / "raw"


def test_parse_raw_dir_finds_nested_workflow_agents(fixtures_dir: Path):
    # rglob must reach agents nested under subagents/workflows/wf_x/.
    events = parse_raw_dir(_raw(fixtures_dir))
    agent_ids = {e.agent_id for e in events}
    assert {"w1", "w2", "w3"} <= agent_ids


def test_load_workflow_journals(fixtures_dir: Path):
    journals = load_workflow_journals(_raw(fixtures_dir))
    assert len(journals) == 1
    assert journals[0]["workflowName"] == "deep-research"


def test_workflow_topology_phase_tree(fixtures_dir: Path):
    raw = _raw(fixtures_dir)
    events = parse_raw_dir(raw)
    journals = load_workflow_journals(raw)
    view = build_session_view(events, None, journals)
    topo = view.topology

    assert topo.mode == SessionMode.WORKFLOW

    # Synthetic phase nodes exist with the PHASE role.
    assert topo.profiles["phase:Scope"].role == AgentRole.PHASE
    assert topo.profiles["phase:Search"].role == AgentRole.PHASE

    # Orchestrator (the session UUID root) → phases → agents.
    root = "11111111-1111-1111-1111-111111111111"
    assert topo.profiles[root].role == AgentRole.ROOT
    assert set(topo.spawn_children[root]) == {"phase:Scope", "phase:Search"}
    assert set(topo.spawn_children["phase:Search"]) == {"w2", "w3"}
    assert topo.spawn_children["phase:Scope"] == ["w1"]

    # Agents are subagents whose display name carries their phase.
    assert topo.profiles["w2"].role == AgentRole.SUBAGENT
    assert topo.profiles["w2"].spawned_by == "phase:Search"
    assert "[Search]" in topo.profiles["w2"].display_name


def test_workflow_cast_excludes_phases_and_counts_real_agents(fixtures_dir: Path):
    raw = _raw(fixtures_dir)
    events = parse_raw_dir(raw)
    view = build_session_view(events, None, load_workflow_journals(raw))

    cast_roles = {a.role for a in view.agents}
    assert AgentRole.PHASE not in cast_roles
    # root + 3 workflow agents, no phase nodes
    assert view.counts["agents"] == 4
    assert view.counts["phases"] == 2


def test_workflow_phase_rollup(fixtures_dir: Path):
    raw = _raw(fixtures_dir)
    events = parse_raw_dir(raw)
    view = build_session_view(events, None, load_workflow_journals(raw))

    phases = {p.title: p for p in view.phases}
    assert phases["Scope"].agents == 1 and phases["Scope"].tokens == 150
    assert phases["Search"].agents == 2 and phases["Search"].tokens == 610
    assert phases["Search"].tool_calls == 6
    assert view.workflow is not None
    assert view.workflow["name"] == "deep-research"
    assert view.workflow["total_tokens"] == 760


def test_workflow_session_summary_mentions_mode_and_phases(fixtures_dir: Path):
    raw = _raw(fixtures_dir)
    events = parse_raw_dir(raw)
    view = build_session_view(events, None, load_workflow_journals(raw))
    md = session_summary(events, view)
    assert "Workflow mode" in md
    assert "## Phases" in md
    assert "Search" in md


def test_collect_copies_nested_tree_and_journal(
    fixtures_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # Build a fake ~/.claude project layout and verify collect copies the nested
    # workflow transcripts + journal (the bug that crashed the original collect).
    sid = "11111111-1111-1111-1111-111111111111"
    home = tmp_path / "home"
    project = home / ".claude" / "projects" / "proj"
    session_dir = project / sid
    (session_dir / "subagents" / "workflows" / "wf_x").mkdir(parents=True)
    (session_dir / "workflows" / "scripts").mkdir(parents=True)

    src = _raw(fixtures_dir)
    shutil.copy2(src / "session.jsonl", project / f"{sid}.jsonl")
    for f in (src / "subagents" / "workflows" / "wf_x").iterdir():
        shutil.copy2(f, session_dir / "subagents" / "workflows" / "wf_x" / f.name)
    shutil.copy2(src / "workflows" / "wf_x.json", session_dir / "workflows" / "wf_x.json")
    (session_dir / "workflows" / "scripts" / "deep-research.js").write_text("// script\n")

    monkeypatch.setenv("HOME", str(home))

    analysis_dir = collect_session(sid, tmp_path / "out")
    raw = analysis_dir / "raw"
    assert (raw / "subagents" / "workflows" / "wf_x" / "agent-w1.jsonl").exists()
    assert (raw / "workflows" / "wf_x.json").exists()
    assert (raw / "workflows" / "scripts" / "deep-research.js").exists()

    # And the collected raw dir parses + classifies as Workflow mode.
    events = parse_raw_dir(raw)
    journal = json.loads((raw / "workflows" / "wf_x.json").read_text())
    assert journal["runId"] == "wf_x"
    view = build_session_view(events, None, load_workflow_journals(raw))
    assert view.topology.mode == SessionMode.WORKFLOW
