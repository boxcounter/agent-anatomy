import shutil
from pathlib import Path

from agent_anatomy.errors import SessionNotFoundError


def find_session_dir(session_id: str) -> Path:
    """Search ~/.claude/projects/ for a session directory."""
    claude_projects = Path.home() / ".claude" / "projects"
    if not claude_projects.is_dir():
        raise SessionNotFoundError(session_id)
    for project_dir in claude_projects.iterdir():
        if not project_dir.is_dir():
            continue
        session_dir = project_dir / session_id
        if session_dir.is_dir():
            return session_dir
    raise SessionNotFoundError(session_id)


def collect_session(session_id: str, output_dir: Path) -> Path:
    """Collect all raw data for a session into output_dir/raw/.

    Returns the analysis directory path.
    """
    analysis_dir = output_dir / "analysis"
    raw_dir = analysis_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    session_dir = find_session_dir(session_id)
    project_dir = session_dir.parent  # project dir contains the main JSONL

    # 1. Copy main transcript (at project_dir level, not inside session_dir)
    jsonl_file = project_dir / f"{session_id}.jsonl"
    if jsonl_file.exists():
        shutil.copy2(jsonl_file, raw_dir / "session.jsonl")

    # 2. Copy subagent sidechains (inside session_dir). Copy the whole tree:
    # Sub-agent mode stores transcripts flat, but Workflow mode nests them under
    # subagents/workflows/wf_<id>/ — a recursive copy handles both.
    subagents_src = session_dir / "subagents"
    subagents_dst = raw_dir / "subagents"
    if subagents_src.is_dir():
        shutil.copytree(subagents_src, subagents_dst, dirs_exist_ok=True)

    # 2b. Copy workflow journals + scripts (Workflow mode). The journal
    # (workflows/wf_<id>.json) is the authoritative topology — the analog of a
    # team's config.json — recording every agent's phase, label, model and usage.
    workflows_src = session_dir / "workflows"
    if workflows_src.is_dir():
        workflows_dst = raw_dir / "workflows"
        workflows_dst.mkdir(exist_ok=True)
        for f in workflows_src.glob("*.json"):
            shutil.copy2(f, workflows_dst / f.name)
        scripts_src = workflows_src / "scripts"
        if scripts_src.is_dir():
            shutil.copytree(scripts_src, workflows_dst / "scripts", dirs_exist_ok=True)

    # 2c. Copy raw tool-results blobs if present (fidelity; not parsed yet).
    tool_results_src = session_dir / "tool-results"
    if tool_results_src.is_dir():
        shutil.copytree(tool_results_src, raw_dir / "tool-results", dirs_exist_ok=True)

    # 3. Copy task files (if session used tasks)
    tasks_dir = Path.home() / ".claude" / "tasks" / session_id
    if tasks_dir.is_dir():
        tasks_dst = raw_dir / "tasks"
        tasks_dst.mkdir(exist_ok=True)
        for f in tasks_dir.iterdir():
            if f.suffix == ".json":
                shutil.copy2(f, tasks_dst / f.name)

    # 4. Copy team config and inboxes
    teams_dir = Path.home() / ".claude" / "teams" / session_id
    if teams_dir.is_dir():
        config_file = teams_dir / "config.json"
        if config_file.exists():
            shutil.copy2(config_file, raw_dir / "team-config.json")

        inboxes_src = teams_dir / "inboxes"
        inboxes_dst = raw_dir / "inboxes"
        if inboxes_src.is_dir():
            inboxes_dst.mkdir(exist_ok=True)
            for f in inboxes_src.iterdir():
                shutil.copy2(f, inboxes_dst / f.name)

    return analysis_dir
