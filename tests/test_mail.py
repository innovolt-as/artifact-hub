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
    monkeypatch.setattr(mail, "send", lambda to, subject, body: sent.update(to=to, subject=subject, body=body) or True)
    main.send_magic_link("a@b.no", "https://hub.test/auth?token=x")
    assert sent["to"] == "a@b.no"
    assert sent["subject"] == f"Logg inn på {main.SITE_NAME}"
    assert "https://hub.test/auth?token=x" in sent["body"] and "15 minutter" in sent["body"]
