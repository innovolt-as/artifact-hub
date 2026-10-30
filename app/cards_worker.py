"""Runs card recipes in V8 for app/cards.py, in a process of its own so the server can kill it.

One JSON line in and one out per job, over stdin/stdout:
  in:  {"source", "docs", "cols", "today", "now", "tz", "time_limit", "memory_limit"}
  out: {"text": str|null} | {"need": [["doc"|"col", path], ...]} | {"error": code, "message"?: str}
Every job gets a fresh V8 context, so nothing carries over from one recipe run to the next. The process writes
{"ready": true} once V8 is loaded, before the first job. A recipe stuck after an `await` cannot be stopped from
here (the promise wait never times out), so the parent kills the process when a job overruns.

Standalone on purpose: it imports nothing from the app and is started with `python -I`.
"""
import contextlib
import json
import sys
import time
from pathlib import Path

from py_mini_racer import JSEvalException, JSOOMException, JSPromise, JSPromiseError, JSTimeoutException, MiniRacer

SHIM = Path(__file__).with_name("cards_shim.js").read_text(encoding="utf-8")
INPUT = ("docs", "cols", "today", "now", "tz")


def _first_line(e: Exception) -> str:
    return str(e).strip().split("\n", 1)[0]


def run(job: dict) -> dict:
    end = time.monotonic() + job["time_limit"]

    def left() -> float:
        return max(end - time.monotonic(), 0.001)

    try:
        with MiniRacer() as ctx:
            ctx.set_hard_memory_limit(job["memory_limit"])
            ctx.eval(SHIM, timeout_sec=left())
            ctx.eval(job["source"], timeout_sec=left())  # separate from the shim, so error line numbers are the recipe's
            answer = ctx.eval("__hubRun(" + json.dumps({k: job[k] for k in INPUT}) + ")", timeout_sec=left())
            if isinstance(answer, JSPromise):
                answer = answer.get(timeout=left())
        return json.loads(answer)
    except JSTimeoutException:
        return {"error": "timeout"}
    except JSOOMException:
        return {"error": "memory"}
    except (JSEvalException, JSPromiseError) as e:
        return {"error": "failed", "message": _first_line(e)}
    except (TypeError, ValueError) as e:  # an answer that is not the shim's JSON string
        return {"error": "failed", "message": _first_line(e)}


def main() -> None:
    with contextlib.suppress(OSError):  # Linux: under memory pressure the kernel kills this worker, not the server
        Path("/proc/self/oom_score_adj").write_text("1000")
    with MiniRacer() as ctx:  # load V8 now, outside any recipe's time
        ctx.eval(SHIM)
    print(json.dumps({"ready": True}), flush=True)
    for line in sys.stdin:
        print(json.dumps(run(json.loads(line))), flush=True)


if __name__ == "__main__":
    main()
