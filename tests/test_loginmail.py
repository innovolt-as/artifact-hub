from email import message_from_bytes, policy

from app import loginmail
from tests.textutil import assert_no_norwegian

ICON = b"\x89PNG..."
LINK = "https://h/auth?token=t"


def test_build_nb():
    m = loginmail.build(LINK, "Innovolt apps", 15, ICON, lang="nb")
    assert m.subject == "Logg inn på Innovolt apps"
    for s in ("Hei!", "Trykk på knappen for å logge inn.", ">Logg inn<",
              "Lenken virker i 15 minutter og kan brukes én gang.", "Virker ikke knappen?", f'href="{LINK}"',
              "cid:icon", "#123566", "#2f5fd1"):
        assert s in m.html
    assert LINK in m.text and "15 minutter" in m.text and "Bruk lenken under for å logge inn." in m.text and "knappen" not in m.text and m.images == {"icon": ICON}


def test_build_en():
    m = loginmail.build(LINK, "Innovolt apps", 15, ICON, lang="en")
    assert m.subject == "Log in to Innovolt apps"
    for s in ("Hi!", ">Log in<", "15 minutes", f'href="{LINK}"'):
        assert s in m.html
    assert "15 minutes" in m.text and LINK in m.text and "Use the link below to log in." in m.text and "button" not in m.text
    assert_no_norwegian(m.html)
    assert_no_norwegian(m.text)


def test_build_default_lang_follows_i18n(english):
    assert loginmail.build(LINK, "S", 15, None).subject == "Log in to S"


def test_minutes_come_from_argument():
    m = loginmail.build(LINK, "S", 7, None, lang="nb")
    assert "7 minutter" in m.html and "7 minutter" in m.text and "15" not in m.text


def test_build_without_icon():
    m = loginmail.build(LINK, "Innovolt apps", 15, None, lang="nb")
    assert m.images == {} and "cid:" not in m.html


def test_site_name_is_escaped():
    m = loginmail.build(LINK, "<b>X</b>", 15, None, lang="nb")
    assert "<b>X</b>" not in m.html and "&lt;b&gt;" in m.html


def test_preview_writes_eml_per_language(tmp_path):
    loginmail.main(["x", str(tmp_path / "out")])
    for lang in ("en", "nb"):
        msg = message_from_bytes((tmp_path / "out" / f"login-{lang}.eml").read_bytes(), policy=policy.default)
        assert msg.get_content_type() == "multipart/alternative"
        assert msg["Subject"]
