import json
import os
import select
import threading
import time
from datetime import UTC, datetime
from pathlib import Path


class KqueueWatcher:
    """Monitor directory trees using kqueue for per-file write notifications."""

    def __init__(
        self,
        inbox_dir: Path,
        tasks_dir: Path,
        output_path: Path,
        poll_interval: float = 5.0,
    ) -> None:
        self.inbox_dir = inbox_dir
        self.tasks_dir = tasks_dir
        self.output_path = output_path
        self.poll_interval = poll_interval
        self._kq = select.kqueue()
        self._fd_to_path: dict[int, Path] = {}
        self._last_snapshot: dict[str, dict[str, str]] = {}
        self._last_poll = time.monotonic()

    def run(self, stop_event: threading.Event) -> None:
        self._scan_and_register()
        self._initial_snapshot()
        self._last_poll = time.monotonic()

        while not stop_event.is_set():
            timeout = min(self.poll_interval, 1.0)
            try:
                events = self._kq.control(None, 128, timeout)
            except OSError:
                break

            if events:
                changed_paths: set[Path] = set()
                for event in events:
                    fd = event.ident
                    path = self._fd_to_path.get(fd)
                    if path is None:
                        self._scan_and_register()
                        continue

                    if event.filter == select.KQ_FILTER_VNODE:
                        changed_paths.add(path)
                        if path.is_dir():
                            self._scan_and_register()

                for path in changed_paths:
                    if path.is_file():
                        self._capture_snapshot(path)

            if not events or (time.monotonic() - self._last_poll >= self.poll_interval):
                self._poll_catchup()
                self._last_poll = time.monotonic()

    def _scan_and_register(self) -> None:
        all_dirs = [self.inbox_dir, self.tasks_dir]
        for base_dir in all_dirs:
            if not base_dir.is_dir():
                continue
            self._register(base_dir)
            for f in base_dir.iterdir():
                self._register(f)

    def _register(self, path: Path) -> None:
        try:
            fd = os.open(str(path), os.O_RDONLY)
        except OSError:
            return

        if fd in self._fd_to_path:
            os.close(fd)
            return

        self._fd_to_path[fd] = path
        ev = select.kevent(
            fd,
            filter=select.KQ_FILTER_VNODE,
            flags=select.KQ_EV_ADD | select.KQ_EV_CLEAR,
            fflags=select.KQ_NOTE_WRITE | select.KQ_NOTE_EXTEND | select.KQ_NOTE_DELETE,
        )
        self._kq.control([ev], 0)

    def _initial_snapshot(self) -> None:
        for base_dir in [self.inbox_dir, self.tasks_dir]:
            if not base_dir.is_dir():
                continue
            for f in base_dir.iterdir():
                if f.is_file() and f.suffix == ".json":
                    self._capture_snapshot(f)

    def _capture_snapshot(self, path: Path) -> None:
        try:
            content_raw = path.read_text()
            content = json.loads(content_raw)
        except (OSError, json.JSONDecodeError):
            return

        kind = "mailbox_snapshot" if "inboxes" in str(path) else "task_snapshot"

        event = {
            "timestamp": datetime.now(UTC).isoformat(),
            "path": str(path),
            "kind": kind,
            "content": content,
        }

        with open(self.output_path, "a") as f:
            f.write(json.dumps(event, default=str) + "\n")

        self._last_snapshot[str(path)] = {
            "timestamp": event["timestamp"],
            "content": json.dumps(content, sort_keys=True),
        }

    def _poll_catchup(self) -> None:
        for base_dir in [self.inbox_dir, self.tasks_dir]:
            if not base_dir.is_dir():
                continue
            for f in base_dir.iterdir():
                if not f.is_file() or f.suffix != ".json":
                    continue
                try:
                    current = json.dumps(json.loads(f.read_text()), sort_keys=True)
                except (OSError, json.JSONDecodeError):
                    continue

                cached = self._last_snapshot.get(str(f))
                if cached is None or cached["content"] != current:
                    self._capture_snapshot(f)


def watch_teams(
    team_name: str,
    output_dir: Path,
    stop_event: threading.Event,
) -> None:
    """Monitor inboxes and tasks for a given team name."""
    home = Path.home()
    inbox_dir = home / ".claude" / "teams" / team_name / "inboxes"
    tasks_dir = home / ".claude" / "tasks" / team_name

    raw_dir = output_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    output_path = raw_dir / "team-events.jsonl"

    watcher = KqueueWatcher(
        inbox_dir=inbox_dir,
        tasks_dir=tasks_dir,
        output_path=output_path,
    )
    watcher.run(stop_event)
