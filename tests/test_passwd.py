import subprocess, sys, os
from app import passwd, main


def test_hash_roundtrip_and_format():
    h = passwd.hash_password("korrekt hest batteri")
    assert h.startswith("scrypt$16384$8$1$") and h.count("$") == 5
    assert passwd.verify_password("korrekt hest batteri", h)
    assert not passwd.verify_password("feil", h)
    assert passwd.hash_password("x") != passwd.hash_password("x")  # salted


def test_verify_tolerates_garbage():
    assert passwd.verify_password("x", "") is False
    assert passwd.verify_password("x", "scrypt$a$b$c$d$e") is False
    assert passwd.verify_password("x", passwd.DUMMY_HASH) is False


def test_table_roundtrip(hub):
    with hub.db() as con:
        assert passwd.get(con, "a@b.no") is None
        at = passwd.set_password(con, " A@B.no ", "passord123", must_change=True, now=1700000000)
        row = passwd.get(con, "a@b.no")
        assert at == 1700000000 and row["must_change"] == 1 and passwd.verify_password("passord123", row["hash"])
        passwd.set_password(con, "a@b.no", "nytt passord", must_change=False, now=1700000001)
        row = passwd.get(con, "a@b.no")
        assert row["must_change"] == 0 and row["updated_at"] == 1700000001
        assert [r["email"] for r in passwd.list_all(con)] == ["a@b.no"]
        passwd.delete(con, "a@b.no")
        assert passwd.get(con, "a@b.no") is None


def test_updated_at_is_monotonic_without_now(hub):
    with hub.db() as con:
        a = passwd.set_password(con, "a@b.no", "pw-1-passord", must_change=True)
        b = passwd.set_password(con, "a@b.no", "pw-1-passord", must_change=True)
        assert b > a and passwd.get(con, "a@b.no")["updated_at"] == b
        # an explicit `now` bypasses the bump and is stored as given
        passwd.set_password(con, "a@b.no", "pw-1-passord", must_change=True, now=5)
        assert passwd.get(con, "a@b.no")["updated_at"] == 5


def test_cli_set_and_list(hub, monkeypatch):
    env = {**os.environ, "DB_PATH": str(hub.DB_PATH)}
    r = subprocess.run([sys.executable, "-m", "app.passwd", "set", "cli@test.no", "--temporary"],
                       input="passord123\npassord123\n", text=True, capture_output=True, env=env)
    assert r.returncode == 0, r.stderr
    assert "Passord satt for cli@test.no" in r.stdout and "må byttes" in r.stdout
    assert "ikke tillatt" in r.stderr  # cli@test.no is not allowed to log in
    r = subprocess.run([sys.executable, "-m", "app.passwd", "list"], text=True, capture_output=True, env=env)
    assert "cli@test.no" in r.stdout and "må byttes" in r.stdout and "scrypt$" not in r.stdout
    r = subprocess.run([sys.executable, "-m", "app.passwd", "set", "cli@test.no"],
                       input="kort\nkort\n", text=True, capture_output=True, env=env)
    assert r.returncode == 2


def test_login_mode_default_and_helper(monkeypatch):
    assert main.LOGIN_MODE == "magic-link" and main.password_mode() is False
    monkeypatch.setattr(main, "LOGIN_MODE", "password")
    assert main.password_mode() is True
