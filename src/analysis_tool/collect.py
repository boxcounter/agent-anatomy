import shutil
from pathlib import Path


def find_session_dir(session_id: str) -> Path:
    """Search ~/.claude/projects/ for a session directory."""
    claude_projects = Path.home() / ".claude" / "projects"
    for project_dir in claude_projects.iterdir():
        if not project_dir.is_dir():
            continue
        session_dir = project_dir / session_id
        if session_dir.is_dir():
            return session_dir
    raise FileNotFoundError(f"Session directory not found for {session_id}")


def collect_session(session_id: str, output_dir: Path) -> Path:
    """Collect all raw data for a session into output_dir/raw/.

    Returns the analysis directory path.
    """
    analysis_dir = output_dir / "analysis"
    raw_dir = analysis_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    session_dir = find_session_dir(session_id)

    # 1. Copy main transcript
    jsonl_file = session_dir / f"{session_id}.jsonl"
    if jsonl_file.exists():
        shutil.copy2(jsonl_file, raw_dir / "session.jsonl")

    # 2. Copy subagent sidechains
    subagents_src = session_dir / session_id / "subagents"
    subagents_dst = raw_dir / "subagents"
    if subagents_src.is_dir():
        subagents_dst.mkdir(exist_ok=True)
        for f in subagents_src.iterdir():
            shutil.copy2(f, subagents_dst / f.name)

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
