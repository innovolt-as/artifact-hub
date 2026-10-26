"""Guard: no Norwegian text outside app/lang/. Add `# i18n-ok` to a line that is not UI text."""
import ast
import re
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"
WORDS = (
    "og|ikke|eller|ingen|logg|slett|ugyldig|ukjent|fant|bare|kunne|legg|fjern|velg|hei|lagre|"
    "avbryt|ferdig|visning|ikoner|siden|personer|alle|apper|passord|tilgang|innlogget|lenken|"
    "feil|bytt|gjenta|favoritter|statistikk|endret|tilbake|koble"
)
NORWEGIAN = re.compile(rf"[æøåÆØÅ]|\b(?:{WORDS})\b", re.IGNORECASE)


def _files(*suffixes):
    for p in sorted(APP.rglob("*")):
        if p.suffix in suffixes and "lang" not in p.relative_to(APP).parts[:1] and "__pycache__" not in p.parts:
            yield p


def _py_hits(path):
    src = path.read_text(encoding="utf-8")
    lines = src.splitlines()
    tree = ast.parse(src)
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant):
                docstrings.add(id(body[0].value))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            if NORWEGIAN.search(node.value) and "i18n-ok" not in lines[node.lineno - 1]:
                yield f"{path.relative_to(APP.parent)}:{node.lineno}: {node.value.strip()[:70]!r}"


def _strip_comments(text):
    text = re.sub(r"\{#.*?#\}", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
    text = re.sub(r"<!--.*?-->", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
    text = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
    return re.sub(r"(?<!:)//.*", "", text)


def _text_hits(path):
    raw = path.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(_strip_comments("\n".join(raw)).splitlines()):
        if NORWEGIAN.search(line) and "i18n-ok" not in raw[i]:
            yield f"{path.relative_to(APP.parent)}:{i + 1}: {raw[i].strip()[:70]!r}"


def test_no_norwegian_outside_lang():
    hits = [h for p in _files(".py") for h in _py_hits(p)]
    hits += [h for p in _files(".html", ".js") for h in _text_hits(p)]
    assert not hits, "Norwegian text outside app/lang/:\n" + "\n".join(hits)
