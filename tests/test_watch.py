import json
import threading
import time
from pathlib import Path

from analysis_tool.watch import KqueueWatcher


def test_kqueue_watcher_detects_file_write(tmp_path: Path):
    """A write to a watched file should be captured."""
    inbox_dir = tmp_path / "inboxes"
    inbox_dir.mkdir()
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()

    output_log = tmp_path / "team-events.jsonl"
    stop_event = threading.Event()

    watcher = KqueueWatcher(
        inbox_dir=inbox_dir,
        tasks_dir=tasks_dir,
        output_path=output_log,
        poll_interval=0.1,
    )

    t = threading.Thread(target=watcher.run, args=(stop_event,), daemon=True)
    t.start()

    time.sleep(0.2)

    (inbox_dir / "agent-x.json").write_text(
        json.dumps([{"from": "lead", "summary": "hello", "read": False}])
    )

    time.sleep(0.3)

    stop_event.set()
    t.join(timeout=2)

    assert output_log.exists()
    lines = output_log.read_text().strip().split("\n")
    assert len(lines) >= 1

    first_event = json.loads(lines[0])
    assert first_event["kind"] == "mailbox_snapshot"
    assert "agent-x.json" in first_event["path"]
    assert len(first_event["content"]) == 1
    assert first_event["content"][0]["from"] == "lead"


def test_kqueue_watcher_poll_catchup(tmp_path: Path):
    """Pre-existing files should be captured via initial scan or poll."""
    inbox_dir = tmp_path / "inboxes"
    inbox_dir.mkdir()
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()

    (inbox_dir / "agent-y.json").write_text(
        json.dumps([{"from": "lead", "summary": "pre-existing", "read": True}])
    )

    output_log = tmp_path / "team-events.jsonl"
    stop_event = threading.Event()

    watcher = KqueueWatcher(
        inbox_dir=inbox_dir,
        tasks_dir=tasks_dir,
        output_path=output_log,
        poll_interval=0.1,
    )

    t = threading.Thread(target=watcher.run, args=(stop_event,), daemon=True)
    t.start()

    time.sleep(0.5)

    stop_event.set()
    t.join(timeout=2)

    lines = output_log.read_text().strip().split("\n")
    assert len(lines) >= 1
