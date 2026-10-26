import smtplib

from app import mail, main


class FakeSMTP:
    instances = []

    def __init__(self, host, port, timeout=None):
        self.host, self.port, self.calls = host, port, []
        FakeSMTP.instances.append(self)

    def __enter__(self): return self
    def __exit__(self, *a): self.calls.append("quit")
    def starttls(self): self.calls.append("starttls")
    def login(self, u, p): self.calls.append(("login", u, p))
    def send_message(self, msg): self.calls.append(("send", msg["To"], msg["Subject"], msg.get_content()))


def test_not_configured_returns_false(monkeypatch):
    monkeypatch.setattr(mail, "SMTP_HOST", "")
    assert mail.configured() is False
    assert mail.send("a@b.no", "s", "b") is False


def test_starttls_login_and_send(monkeypatch):
    FakeSMTP.instances.clear()
    monkeypatch.setattr(mail, "SMTP_HOST", "smtp.test")
    monkeypatch.setattr(mail, "SMTP_PORT", 587)
    monkeypatch.setattr(mail, "SMTP_USER", "u")
    monkeypatch.setattr(mail, "SMTP_PASS", "p")
    monkeypatch.setattr(mail, "SMTP_FROM", "Hub <hub@test>")
    monkeypatch.setattr(mail, "SMTP_TLS", "starttls")
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    assert mail.send("a@b.no", "Hei", "Body") is True
    s = FakeSMTP.instances[0]
    assert (s.host, s.port) == ("smtp.test", 587)
    assert s.calls == ["starttls", ("login", "u", "p"), ("send", "a@b.no", "Hei", "Body\n"), "quit"]


def test_ssl_uses_smtp_ssl(monkeypatch):
    FakeSMTP.instances.clear()
    monkeypatch.setattr(mail, "SMTP_HOST", "smtp.test")
    monkeypatch.setattr(mail, "SMTP_TLS", "ssl")
    monkeypatch.setattr(mail, "SMTP_USER", "")
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
    assert mail.send("a@b.no", "s", "b") is True
    assert "starttls" not in FakeSMTP.instances[0].calls and ("login", "u", "p") not in FakeSMTP.instances[0].calls


def test_login_without_smtp_logs_link_and_still_says_sent(client, caplog):
    r = client.post("/login", data={"email": "user@test.no"})
    assert r.status_code == 200 and "user@test.no" in r.text
    assert any("magic link for user@test.no" in rec.getMessage() and "/auth?token=" in rec.getMessage()
               for rec in caplog.records)


def test_magic_link_mail_text(monkeypatch):
    sent = {}

    def fake(to, subject, text, html=None, images=None, sender_name=None):
        sent.update(to=to, subject=subject, text=text, html=html, images=images, sender_name=sender_name)
        return True

    monkeypatch.setattr(mail, "send", fake)
    main.send_magic_link("a@b.no", "https://hub.test/auth?token=x")
    assert sent["to"] == "a@b.no"
    assert sent["subject"] == f"Logg inn på {main.SITE_NAME}"
    assert sent["sender_name"] == main.SITE_NAME
    minutes = main.MAGIC_TTL // 60
    assert "https://hub.test/auth?token=x" in sent["text"] and f"{minutes} minutter" in sent["text"]
    assert 'href="https://hub.test/auth?token=x"' in sent["html"] and f"{minutes} minutter" in sent["html"]
    assert set(sent["images"]) == {"icon"} and sent["images"]["icon"][:4] == b"\x89PNG"


def test_magic_link_uses_branded_icon_and_survives_unreadable_icon(monkeypatch):
    sent = {}
    monkeypatch.setattr(mail, "send", lambda to, subject, text, **kw: sent.update(kw) or True)
    main.BRANDING_DIR.mkdir(parents=True, exist_ok=True)
    icon = main.BRANDING_DIR / "apple-touch-icon.png"
    icon.write_bytes(b"\x89PNGbranded")
    main.send_magic_link("a@b.no", "https://hub.test/auth?token=x")
    assert sent["images"] == {"icon": b"\x89PNGbranded"}
    icon.unlink()
    # static_file() falls back to the default for a non-file, so point it at a folder to get an OSError on read
    monkeypatch.setattr(main, "static_file", lambda name: main.BRANDING_DIR)
    main.send_magic_link("a@b.no", "https://hub.test/auth?token=x")
    assert sent["images"] == {} and "cid:" not in sent["html"]


def test_sender_name(monkeypatch):
    monkeypatch.setattr(mail, "SMTP_FROM", "hub@x")
    assert mail.sender("Hub") == "Hub <hub@x>"
    assert mail.sender(None) == "hub@x" and mail.sender("") == "hub@x"
    monkeypatch.setattr(mail, "SMTP_FROM", "Navn <hub@x>")
    assert mail.sender("Hub") == "Navn <hub@x>"


def test_sender_name_non_ascii(monkeypatch):
    monkeypatch.setattr(mail, "SMTP_FROM", "hub@x")
    msg = mail.build_message("a@b.no", "s", "t", sender_name="Bøkene")
    assert msg["From"].addresses[0].display_name == "Bøkene"
    assert msg["From"].addresses[0].addr_spec == "hub@x"


def test_html_with_inline_icon():
    msg = mail.build_message("a@b.no", "s", "plain", html='<p><img src="cid:icon"></p>', images={"icon": b"\x89PNGx"})
    assert msg.get_content_type() == "multipart/alternative"
    plain, rel = msg.get_payload()
    assert plain.get_content_type() == "text/plain"
    assert rel.get_content_type() == "multipart/related"
    html, img = rel.get_payload()
    assert html.get_content_type() == "text/html"
    assert img.get_content_type() == "image/png" and img["Content-ID"] == "<icon>"


def test_plain_only_message():
    msg = mail.build_message("a@b.no", "s", "plain")
    assert msg.get_content_type() == "text/plain"


def test_send_passes_html_and_sender(monkeypatch):
    FakeSMTP.instances.clear()
    sent = []
    monkeypatch.setattr(mail, "SMTP_HOST", "smtp.test")
    monkeypatch.setattr(mail, "SMTP_USER", "")
    monkeypatch.setattr(mail, "SMTP_TLS", "none")
    monkeypatch.setattr(mail, "SMTP_FROM", "hub@x")
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(FakeSMTP, "send_message", lambda self, m: sent.append(m))
    assert mail.send("a@b.no", "s", "t", html="<p>t</p>", sender_name="Hub") is True
    assert sent[0]["From"] == "Hub <hub@x>" and sent[0].get_content_type() == "multipart/alternative"


def test_message_has_date_and_message_id(monkeypatch):
    monkeypatch.setattr(mail, "SMTP_FROM", "Hub <hub@example.test>")
    m = mail.build_message("a@b.no", "s", "b")
    assert m["Date"] and m["Message-ID"].endswith("@example.test>")
    monkeypatch.setattr(mail, "SMTP_FROM", "nodomain")
    assert mail.build_message("a@b.no", "s", "b")["Message-ID"].endswith("@localhost>")
