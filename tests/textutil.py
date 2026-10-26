"""visible_text(): the text a person sees on a page, for the golden-file tests."""
import re
from html.parser import HTMLParser

ATTRS = ("title", "placeholder", "aria-label", "alt")
SKIP = ("script", "style")


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in SKIP:
            self._skip += 1
        for k, v in attrs:
            if k in ATTRS and v and v.strip():
                self.lines.append(f"@{k}: {' '.join(v.split())}")

    def handle_endtag(self, tag):
        if tag in SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            text = " ".join(data.split())
            if text:
                self.lines.append(text)


def visible_text(body: str) -> str:
    p = _Text()
    p.feed(body)
    p.close()
    return "\n".join(p.lines) + "\n"


_NORWEGIAN = re.compile(r"[æøåÆØÅ]|\b(?:Logg|Ingen|Velg|Legg|Fjern|Lagre|Bytt|passord|apper|siden|Hei)\b")


def assert_no_norwegian(body: str) -> None:
    """Fail if the visible text of `body` has Norwegian letters or common Norwegian words."""
    text = visible_text(body)
    m = _NORWEGIAN.search(text)
    assert not m, f"Norwegian text left: {m.group()!r} in: {text[max(0, m.start() - 40):m.end() + 40]!r}"
