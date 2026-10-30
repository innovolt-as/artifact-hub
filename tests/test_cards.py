"""Card recipes: app JavaScript run in a killable V8 worker to compute the line on the front page card."""
import time
from pathlib import Path

import pytest

from app import cards


def _run(src, data=None, cols=None, **kw):
    data, cols = data or {}, cols or {}

    def read(kind, path):
        if kind == "doc":
            return data.get(path)
        return [{"id": k, "data": v} for k, v in sorted(cols.get(path, {}).items())]

    return cards.run_recipe(src, read, today=kw.get("today", "2026-10-28"), now_ms=kw.get("now_ms", 0),
                            tz=kw.get("tz", "Europe/Oslo"))


def test_returns_text_from_docs():
    src = ("async function hubCard({db, today}) { const d = await db.doc(`days/${today}`).get();"
           " return d.exists ? d.data().k + ' kcal' : 'tom'; }")
    assert _run(src, {"days/2026-10-28": {"k": 900}}) == cards.CardResult("900 kcal", None)
    assert _run(src).text == "tom"


def test_reads_chain_over_rounds():  # settings -> path from settings
    src = ("async function hubCard({db}) { const s = (await db.doc('settings/main').get()).data();"
           " return (await db.doc('x/' + s.id).get()).data().v; }")
    assert _run(src, {"settings/main": {"id": "a"}, "x/a": {"v": "ok"}}).text == "ok"


def test_collection_query_where_order_limit():
    src = ("async function hubCard({db}) { const q = await db.collection('t').where('done','==',false)"
           ".orderBy('n','desc').limit(2).get(); return q.docs.map(d => d.id).join(',') + '/' + q.size; }")
    cols = {"t": {"a": {"done": False, "n": 1}, "b": {"done": True, "n": 9}, "c": {"done": False, "n": 5},
                  "d": {"done": False}}}
    assert _run(src, cols=cols).text == "c,a/2"  # missing field sorts last, same as hub.js


def test_null_empty_and_wrong_type():
    assert _run("function hubCard(){ return null }") == cards.CardResult(None, None)
    assert _run("function hubCard(){ return '' }") == cards.CardResult(None, None)  # the shim turns "" into null
    assert _run("function hubCard(){ return 5 }").error == "not_text"
    assert _run("const x = 1;").error == "no_function"
    assert _run("function hubCard( {").error.startswith("failed")
    assert _run("function hubCard(){ throw new Error('au') }").error.startswith("failed")


def test_read_only_and_no_browser():
    src = ("function hubCard({db}) { return [typeof db.doc('a/b').set, typeof db.collection('a').add,"
           " typeof window, typeof fetch, typeof document].join(',') }")
    assert _run(src).text == "undefined,undefined,undefined,undefined,undefined"


def test_sync_loop_times_out():
    t = time.monotonic()
    assert _run("function hubCard(){ while(true){} }").error == "timeout"
    assert time.monotonic() - t < 2


def test_hang_after_await_is_killed_and_next_run_works():
    t = time.monotonic()
    assert _run("async function hubCard(){ await null; while(true){} }").error == "timeout"
    assert time.monotonic() - t < 2
    assert _run("function hubCard(){ return 'igjen' }").text == "igjen"


def test_memory_limit():
    assert _run("function hubCard(){ const a=[]; while(true) a.push(new Array(1e5).fill(1)) }").error in (
        "memory", "timeout")
    assert _run("function hubCard(){ return 'ok' }").text == "ok"


def test_no_state_between_runs():
    src = "var seen; function hubCard(){ const was = globalThis.seen; globalThis.seen = 'A'; return String(was) }"
    assert _run(src).text == "undefined" and _run(src).text == "undefined"


def test_too_many_reads():
    src = "async function hubCard({db}) { for (let i = 0; ; i++) await db.doc('x/' + i).get(); }"
    assert _run(src).error == "too_many_reads"


def test_bad_path_from_reader():
    def read(kind, path):
        raise ValueError("bad")

    assert cards.run_recipe("async function hubCard({db}){ await db.doc('a/b').get() }", read,
                            today="2026-10-28", now_ms=0, tz="UTC").error == "bad_path"


def test_inputs_passed():
    src = ("function hubCard({today, now, timeZone}) {"
           " return [today, now, timeZone, (1572).toLocaleString('no-NO')].join('|') }")
    # Intl groups the digits with a no-break space
    assert _run(src, now_ms=123, tz="Europe/Oslo").text == "2026-10-28|123|Europe/Oslo|1\u00a0572"


def test_today_and_day_of():
    ts = 1793142000  # 2026-10-28 00:00 Oslo (CET) = 2026-10-27 23:00 UTC
    assert cards.today("Europe/Oslo", ts) == ("2026-10-28", "Europe/Oslo")
    assert cards.day_of(ts, "UTC") == "2026-10-27"
    assert cards.today("Ikke/Sone", ts)[0] == time.strftime("%Y-%m-%d", time.localtime(ts))


def test_failed_message_is_one_short_line():
    # the recipe is evaluated on its own, so line numbers are the recipe's
    assert _run("\n\nfunction hubCard( {").error == "failed: <anonymous>:3: SyntaxError: Unexpected end of input"
    assert _run("function hubCard(){ throw new Error('x'.repeat(500)) }").error == "failed: Error: " + "x" * 193


def test_lone_surrogate_becomes_question_mark():  # it could not be sent as UTF-8 on the front page
    assert _run("function hubCard(){ return 'a\\ud800b' }").text == "a?b"


def test_slow_reads_stop_at_the_deadline():  # reads count against the time; the idle worker is not killed
    _run("function hubCard(){ return 'up' }")
    pid, calls = cards._worker.proc.pid, []

    def read(kind, path):
        calls.append(path)
        time.sleep(0.05)
        return {"v": 1}

    src = "async function hubCard({db}) { await Promise.all([...Array(20).keys()].map(i => db.doc('x/' + i).get())) }"
    t = time.monotonic()
    assert cards.run_recipe(src, read, today="2026-10-28", now_ms=0, tz="UTC").error == "timeout"
    assert time.monotonic() - t < 0.5 and len(calls) < 20
    assert cards._worker.proc is not None and cards._worker.proc.pid == pid


def test_too_many_paths_in_one_round():
    calls = []

    def read(kind, path):
        calls.append(path)

    src = (f"async function hubCard({{db}}) {{ await Promise.all([...Array({cards.MAX_READS + 1}).keys()]"
           ".map(i => db.doc('x/' + i).get())); return 'all read' }")
    assert cards.run_recipe(src, read, today="2026-10-28", now_ms=0, tz="UTC").error == "too_many_reads"
    assert calls == []


GONE = ("ArrayBuffer", "SharedArrayBuffer", "DataView", "WebAssembly", "Atomics", "Int8Array", "Uint8Array",
        "Uint8ClampedArray", "Int16Array", "Uint16Array", "Int32Array", "Uint32Array", "Float16Array", "Float32Array",
        "Float64Array", "BigInt64Array", "BigUint64Array")


def test_no_buffers_outside_the_heap():  # the memory limit only covers the V8 heap
    r = _run("function hubCard(){ return String(new Uint8Array(300e6).fill(1).length) }")
    assert r.text is None and r.error
    src = "function hubCard(){ return [" + ", ".join(f"typeof {n}" for n in GONE) + "].join() }"
    assert _run(src).text == ",".join(["undefined"] * len(GONE))


def test_kernel_picks_the_worker_under_memory_pressure():
    _run("function hubCard(){ return 'up' }")
    adj = Path(f"/proc/{cards._worker.proc.pid}/oom_score_adj")
    if not adj.exists():
        pytest.skip("no /proc here")
    assert adj.read_text().strip() == "1000"


def test_worker_that_does_not_start_gives_an_error(monkeypatch, tmp_path):
    cards._worker.stop()
    monkeypatch.setattr(cards, "WORKER", tmp_path / "missing.py")  # exits before it is ready
    assert _run("function hubCard(){ return 'x' }") == cards.CardResult(None, "failed: worker")
    monkeypatch.setattr(cards.sys, "executable", str(tmp_path / "no-python"))  # cannot be started at all
    assert _run("function hubCard(){ return 'x' }") == cards.CardResult(None, "failed: worker")
