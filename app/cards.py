"""Card recipes: an app's own JavaScript that computes the line on its front page card from the app's stored data.

The recipe runs in V8 (mini-racer) in a worker process (cards_worker.py), with a fresh context per run, a time
limit for all rounds together and a memory limit. It reads through a read-only `db` (cards_shim.js) and only sees
the data run_recipe hands it: a read of a path it does not have yet ends the round with the paths it needs, the
caller's `read` fetches them, and the recipe runs again with them, at most MAX_ROUNDS times. V8 stops a recipe that
runs past the deadline itself and the worker answers "timeout"; one that hangs after an `await` cannot be stopped
inside V8, so a job still running GRACE seconds after the deadline gets the worker process killed.
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
MAX_READS = 50  # paths one round may ask for
START_LIMIT = 10.0  # seconds a new worker may take to load V8; not counted in any recipe's time
LINE_MAX = 1 << 20  # characters read of one answer line; the worker cuts its strings far below this
GRACE = 0.05  # seconds past the deadline before a worker is killed, so V8's own timeout answers first and it stays
RETRY_AFTER = 30.0  # seconds after a worker failed to start before the next try; meanwhile recipes fail at once
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
        self.retry_at = 0.0  # time.monotonic() before which no new start is tried

    def start(self) -> bool:
        """Have a running worker that has loaded V8. False if it does not come up, and then without trying again for
        RETRY_AFTER seconds, so a worker that cannot start does not cost every recipe on the page a new try."""
        if self.proc is not None and self.proc.poll() is None:
            return True
        self.stop()  # a worker that died on its own
        if time.monotonic() < self.retry_at:
            return False
        try:
            self.proc = subprocess.Popen([sys.executable, "-I", str(WORKER)], stdin=subprocess.PIPE,
                                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
            if self._answer(time.monotonic() + START_LIMIT) == {"ready": True}:
                return True
        except (OSError, ValueError):  # could not be started, or exited before it was ready
            pass
        self.stop()
        self.retry_at = time.monotonic() + RETRY_AFTER
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
        """The worker's next line as JSON; None when nothing came by `deadline`. ValueError at EOF, garbage or a line
        longer than LINE_MAX, whose rest is never read (the worker is then killed)."""
        ready, _, _ = select.select([self.proc.stdout], [], [], max(deadline - time.monotonic(), 0))
        if not ready:
            return None
        line = self.proc.stdout.readline(LINE_MAX + 1)
        if len(line) > LINE_MAX:
            raise ValueError("answer line too long")
        return json.loads(line)

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
    raises makes the result "bad_path". The reads count against TIME_LIMIT, and a round that asks for more than
    MAX_READS paths gives "too_many_reads".
    """
    docs: dict[str, object] = {}
    cols: dict[str, object] = {}
    with _worker.lock:
        if not _worker.start():
            return CardResult(None, "failed: worker")
        deadline = time.monotonic() + TIME_LIMIT  # the clock starts once the worker is up
        for _ in range(MAX_ROUNDS):
            if time.monotonic() >= deadline:  # the reads used up the time; the worker is idle and stays
                return CardResult(None, "timeout")
            job = {"source": source, "docs": docs, "cols": cols, "today": today, "now": now_ms, "tz": tz,
                   "time_limit": deadline - time.monotonic(), "memory_limit": MEMORY_LIMIT}
            answer = _worker.ask(job, deadline + GRACE)
            if "need" not in answer:
                return _result(answer)
            need = answer["need"]
            if isinstance(need, list) and len(need) > MAX_READS:
                return CardResult(None, "too_many_reads")
            try:
                for kind, path in need:
                    if time.monotonic() >= deadline:
                        return CardResult(None, "timeout")
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
