"""App code lock storage: codes, per-app choices and the shared attempt limit (app/applock.py)."""
import importlib
from concurrent.futures import ThreadPoolExecutor

import pytest

from app import applock, passwd

E ="martin@test.no"


def Check(*args, **kwargs):
    # looked up late: one test reloads the module, which makes a new dataclass
    return applock.Check(*args, **kwargs)


@pytest.fixture
def con(hub):
    with hub.db() as c:
        yield c


@pytest.fixture
def scrypt_calls(monkeypatch):
    """Count the runs of passwd.verify_password; the real function still does the work."""
    calls = []
    real = passwd.verify_password

    def counting(password, stored):
        calls.append(password)
        return real(password, stored)

    monkeypatch.setattr(passwd, "verify_password", counting)
    return calls


def test_valid_code():
    for ok in ("0000", "0042", "9999"):
        assert applock.valid_code(ok)
    for bad in ("123", "12345", "12a4", "1234\n", "١٢٣٤", 1234, None, ""):
        assert not applock.valid_code(bad)


def test_set_code_stores_a_hash_not_the_code(con):
    applock.set_code(con, E, "1234")
    stored = applock.get(con, E)["hash"]
    assert stored.startswith("scrypt$") and "1234" not in stored


def test_updated_at_moves_within_the_same_second(con):
    first = applock.set_code(con, E, "1234")
    assert applock.set_code(con, E, "4321") > first


def test_email_is_normalised(con):
    applock.set_code(con, " Martin@Test.no ", "1234")
    assert applock.get(con, "martin@test.no") is not None
    applock.set_locked(con, " Martin@Test.no ", "a", True)
    assert applock.is_locked(con, "martin@test.no", "a")


def test_right_code(hub, con):
    applock.set_code(con, E, "1234")
    con.commit()
    assert applock.check(hub.db, E, "1234") == Check(True)


def test_wrong_code(hub, con):
    applock.set_code(con, E, "1234")
    con.commit()
    assert applock.check(hub.db, E, "4321") == Check(False)
    assert applock.get(con, E)["fails"] == 1


def test_no_code_is_wrong(hub):
    assert applock.check(hub.db, E, "1234") == Check(False)


def test_malformed_code_is_wrong_and_not_counted(hub, con, scrypt_calls):
    applock.set_code(con, E, "1234")
    con.commit()
    assert applock.check(hub.db, E, "12") == Check(False)
    assert applock.get(con, E)["fails"] == 0
    assert scrypt_calls == []


def _block(hub, now=1000):
    for _ in range(5):
        res = applock.check(hub.db, E, "0000", now=now)
    return res


def test_five_wrong_blocks_for_15_minutes(hub, con):
    applock.set_code(con, E, "1234")
    con.commit()
    assert _block(hub) == Check(False, wait=900)
    assert applock.check(hub.db, E, "0000", now=1000) == Check(False, wait=900)


def test_a_block_refuses_the_right_code_without_scrypt(hub, con, scrypt_calls):
    applock.set_code(con, E, "1234")
    con.commit()
    _block(hub)
    scrypt_calls.clear()
    assert applock.check(hub.db, E, "1234", now=1001) == Check(False, wait=899)
    assert scrypt_calls == []


def test_the_block_ends(hub, con):
    applock.set_code(con, E, "1234")
    con.commit()
    _block(hub)
    assert applock.check(hub.db, E, "1234", now=1900).ok
    _block(hub, now=2000)
    assert applock.check(hub.db, E, "0000", now=2900) == Check(False)
    row = applock.get(con, E)
    assert row["fails"] == 1 and row["blocked_until"] == 0


def test_the_right_code_resets_the_count(hub, con):
    applock.set_code(con, E, "1234")
    con.commit()
    for _ in range(4):
        applock.check(hub.db, E, "0000", now=1000)
    assert applock.check(hub.db, E, "1234", now=1000).ok
    for _ in range(4):
        assert applock.check(hub.db, E, "0000", now=1000) == Check(False)


def test_the_fifth_try_may_be_right(hub, con):
    applock.set_code(con, E, "1234")
    con.commit()
    for _ in range(4):
        applock.check(hub.db, E, "0000", now=1000)
    assert applock.check(hub.db, E, "1234", now=1000).ok
    assert applock.get(con, E)["fails"] == 0


def test_parallel_tries_cannot_pass_the_limit(hub, con, scrypt_calls):
    applock.set_code(con, E, "1234")
    con.commit()
    with ThreadPoolExecutor(20) as pool:
        results = list(pool.map(lambda _: applock.check(hub.db, E, "0000"), range(20)))
    assert len(scrypt_calls) == 5
    assert not any(r.ok for r in results)


def test_the_block_survives_a_restart(hub, con):
    applock.set_code(con, E, "1234")
    con.commit()
    _block(hub, now=1000)
    importlib.reload(applock)
    assert not applock.check(hub.db, E, "1234", now=1001).ok


def test_must_change_is_reported(hub, con):
    applock.set_code(con, E, "1234", must_change=True)
    con.commit()
    assert applock.check(hub.db, E, "1234") == Check(True, must_change=True)


def test_reset(hub, con):
    old = applock.set_code(con, E, "1234")
    con.commit()
    _block(hub)
    code = applock.reset(con, E)
    con.commit()
    assert applock.valid_code(code)
    row = applock.get(con, E)
    assert row["must_change"] == 1 and row["updated_at"] > old
    assert row["fails"] == 0 and row["blocked_until"] == 0
    assert applock.check(hub.db, E, code, now=1001).ok
    if code != "1234":
        assert not applock.check(hub.db, E, "1234").ok


def test_reset_without_a_code_changes_nothing(con):
    assert applock.reset(con, E) is None
    assert applock.get(con, E) is None


def test_locks_are_per_user_and_app(con):
    applock.set_locked(con, E, "a", True)
    assert applock.is_locked(con, E, "a")
    assert not applock.is_locked(con, E, "b")
    assert not applock.is_locked(con, "other@test.no", "a")
    applock.set_locked(con, E, "b", True)
    assert applock.locked_slugs(con, E) == {"a", "b"}


def test_set_locked_off(con):
    applock.set_locked(con, E, "a", True)
    applock.set_locked(con, E, "a", False)
    assert applock.locked_slugs(con, E) == set()


def test_set_locked_twice_is_one_row(con):
    applock.set_locked(con, E, "a", True)
    applock.set_locked(con, E, "a", True)
    assert con.execute("SELECT COUNT(*) FROM app_locks").fetchone()[0] == 1


def test_rename_moves_every_users_lock(con):
    applock.set_locked(con, E, "old", True)
    applock.set_locked(con, "b@test.no", "old", True)
    applock.set_locked(con, "b@test.no", "new", True)  # the target already exists
    applock.rename(con, "old", "new")
    assert applock.locked_slugs(con, E) == {"new"}
    assert applock.locked_slugs(con, "b@test.no") == {"new"}
    assert con.execute("SELECT COUNT(*) FROM app_locks").fetchone()[0] == 2


def test_list_all_and_emails(con):
    applock.set_code(con, "b@test.no", "1234")
    applock.set_code(con, E, "1234")
    applock.set_locked(con, E, "a", True)
    applock.set_locked(con, E, "b", True)
    rows = applock.list_all(con)
    assert [(r["email"], r["apps"]) for r in rows] == [("b@test.no", 0), (E, 2)]
    assert applock.emails(con) == {E, "b@test.no"}


@pytest.fixture
def cli_db(hub, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(hub.DB_PATH))


def test_cli_reset_prints_the_code_once(hub, con, cli_db, capsys):
    applock.set_code(con, E, "1234")
    con.commit()
    assert applock.main(["reset", E]) == 0
    out = capsys.readouterr().out
    assert E in out
    code = out.split(": ")[1].split(".")[0]
    assert applock.valid_code(code)
    assert applock.check(hub.db, E, code).ok


def test_cli_reset_without_a_code_fails(hub, cli_db, capsys):
    assert applock.main(["reset", E]) == 1
    assert E in capsys.readouterr().err
    with hub.db() as con:
        assert applock.get(con, E) is None


def test_cli_list_shows_no_hash(con, cli_db, capsys):
    applock.set_code(con, E, "1234")
    applock.set_locked(con, E, "a", True)
    con.commit()
    assert applock.main(["list"]) == 0
    out = capsys.readouterr().out
    assert E in out and "1" in out and "scrypt$" not in out
