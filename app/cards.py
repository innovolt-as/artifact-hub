"""Card recipes: an app's own JavaScript that computes the line on its front page card from the app's stored data.

The recipe runs in V8 (mini-racer) in a worker process (cards_worker.py), with a fresh context per run, a time
limit for all rounds together and a memory limit. It reads through a read-only `db` (cards_shim.js) and only sees
the data run_recipe hands it: a read of a path it does not have yet ends the round with the paths it needs, the
caller's `read` fetches them, and the recipe runs again with them, at most MAX_ROUNDS times. A recipe that hangs
after an `await` cannot be stopped inside V8, so a job that overruns gets the worker process killed.
"""
import contextlib
import json
import os
import select
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

TIME_LIMIT = 0.25  # seconds for all rounds of one recipe together
MEMORY_LIMIT = 32 * 1024 * 1024
MAX_ROUNDS = 5
START_LIMIT = 10.0  # seconds a new worker may take to load V8; not counted in any recipe's time
WORKER = Path(__file__).with_name("cards_worker.py")
CODES = ("timeout", "memory", "no_function", "not_text")  # the worker's error codes besides "failed"
BROKEN = {"error": "failed", "message": "worker"}  # the worker died or did not answer with a JSON object


@dataclass(frozen=True)
class CardResult:
    text: str | None
    error: str | None


class _Worker:
    """The worker process, started when first needed and again after it has been killed. One job at a time."""

    def __init__(self):
        self.lock = threading.Lock()
        self.proc: subprocess.Popen | None = None

    def start(self) -> bool:
        """Have a running worker that has loaded V8. False if it does not come up."""
        if self.proc is not None and self.proc.poll() is None:
            return True
        self.stop()  # a worker that died on its own
        self.proc = subprocess.Popen([sys.executable, "-I", str(WORKER)], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
        if self._answer(time.monotonic() + START_LIMIT) == {"ready": True}:
            return True
        self.stop()
        return False

    def stop(self) -> None:
        if self.proc is not None:
            self.proc.kill()
            self.proc.wait()
            for pipe in (self.proc.stdin, self.proc.stdout):
                with contextlib.suppress(OSError):  # stdin may hold a line the dead worker never read
                    pipe.close()
            self.proc = None

    def _answer(self, deadline: float) -> object:
        """The worker's next line as JSON; None when nothing came by `deadline`. ValueError at EOF or garbage."""
        ready, _, _ = select.select([self.proc.stdout], [], [], max(deadline - time.monotonic(), 0))
        return json.loads(self.proc.stdout.readline()) if ready else None

    def ask(self, job: dict, deadline: float) -> dict:
        """Run one job. A worker that is late, dead or answers garbage is killed."""
        try:
            self.proc.stdin.write(json.dumps(job) + "\n")
            self.proc.stdin.flush()
            answer = self._answer(deadline)
            if isinstance(answer, dict):
                return answer
            failure = {"error": "timeout"} if answer is None else BROKEN
        except (OSError, ValueError):
            failure = BROKEN
        self.stop()
        return failure


_worker = _Worker()


def _clean(s: str) -> str:
    """Lone surrogates (valid in JS strings, not in UTF-8) become "?", so the text can be sent as a page."""
    return s.encode("utf-8", "replace").decode("utf-8")


def _result(answer: dict) -> CardResult:
    """The CardResult for a worker's final answer. Anything off-protocol counts as a broken worker."""
    text = answer.get("text")
    if "text" in answer and (text is None or isinstance(text, str)):
        return CardResult(None if text is None else _clean(text), None)
    code = answer.get("error")
    if code in CODES:
        return CardResult(None, code)
    message = answer.get("message") if code == "failed" else None
    return CardResult(None, "failed: " + _clean(message if isinstance(message, str) else "worker")[:200])


def run_recipe(source: str, read: Callable[[str, str], object], *, today: str, now_ms: int, tz: str) -> CardResult:
    """Run the recipe `source` (it defines hubCard) and return its line or an error code.

    read("doc", path) gives the document's data or None, read("col", path) gives [{"id", "data"}]; anything it
    raises makes the result "bad_path".
    """
    docs: dict[str, object] = {}
    cols: dict[str, object] = {}
    with _worker.lock:
        if not _worker.start():
            return CardResult(None, "failed: worker")
        deadline = time.monotonic() + TIME_LIMIT  # the clock starts once the worker is up
        for _ in range(MAX_ROUNDS):
            job = {"source": source, "docs": docs, "cols": cols, "today": today, "now": now_ms, "tz": tz,
                   "time_limit": max(deadline - time.monotonic(), 0), "memory_limit": MEMORY_LIMIT}
            answer = _worker.ask(job, deadline)
            if "need" not in answer:
                return _result(answer)
            try:
                for kind, path in answer["need"]:
                    if kind not in ("doc", "col") or not isinstance(path, str):
                        raise ValueError(kind)
                    (docs if kind == "doc" else cols)[path] = read(kind, path)
            except Exception:
                return CardResult(None, "bad_path")
        return CardResult(None, "too_many_reads")


def _zone(tz: str | None) -> tuple[ZoneInfo | None, str]:
    """The viewer's zone and its name; (None, the server's zone name) when tz is missing or unknown."""
    if tz:
        try:
            return ZoneInfo(tz), tz
        except (ZoneInfoNotFoundError, ValueError):
            pass
    return None, os.environ.get("TZ") or "UTC"


def day_of(ts: float, tz: str | None) -> str:
    """The date ("YYYY-MM-DD") at timestamp `ts` in zone `tz`, or in the server's local time without a valid tz."""
    return datetime.fromtimestamp(ts, _zone(tz)[0]).strftime("%Y-%m-%d")


def today(tz: str | None, now: float) -> tuple[str, str]:
    """Today's date at `now` in zone `tz` and the name of the zone that was used (see day_of)."""
    zone, name = _zone(tz)
    return datetime.fromtimestamp(now, zone).strftime("%Y-%m-%d"), name
