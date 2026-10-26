import json
import string

import pytest

from app import i18n


def _files():
    return {lang: json.loads((i18n.LANG_DIR / f"{lang}.json").read_text(encoding="utf-8")) for lang in i18n.available()}


def _fields(v):
    items = v if isinstance(v, list) else [v]
    return [sorted(f for _, f, _, _ in string.Formatter().parse(s) if f) for s in items]


def test_resolve():
    assert i18n.resolve(None) == i18n.resolve("") == "en"
    assert i18n.resolve("NB ") == i18n.resolve(" No") == "nb"
    with pytest.raises(SystemExit, match=r"HUB_LANG must be one of: en, nb \(got 'xx'\)"):
        i18n.resolve("xx")


def test_resolve_matches_file_names_with_capitals(tmp_path, monkeypatch):
    (tmp_path / "pt-BR.json").write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(i18n, "LANG_DIR", tmp_path)
    assert i18n.resolve("pt-BR") == i18n.resolve("pt-br") == "pt-BR"


def test_broken_language_file_stops_at_load(tmp_path, monkeypatch):
    (tmp_path / "en.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "xx.json").write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(i18n, "LANG_DIR", tmp_path)
    i18n._load.cache_clear()
    try:
        with pytest.raises(SystemExit, match=r"xx\.json"):
            i18n.resolve_and_load("xx")
        assert i18n.resolve_and_load("en") == "en"
    finally:
        i18n._load.cache_clear()


def test_nb_and_en_have_the_same_keys_and_types():
    f = _files()
    assert f["nb"].keys() == f["en"].keys()
    assert {k: type(v) for k, v in f["nb"].items()} == {k: type(v) for k, v in f["en"].items()}


def test_no_language_has_keys_en_lacks():
    f = _files()
    for lang, d in f.items():
        assert not set(d) - set(f["en"]), lang


def test_placeholders_match_en():
    f = _files()
    for lang, d in f.items():
        for k, v in d.items():
            assert _fields(v) == _fields(f["en"][k]), (lang, k)


def test_files_are_sorted_and_end_with_newline():
    for lang in i18n.available():
        text = (i18n.LANG_DIR / f"{lang}.json").read_text(encoding="utf-8")
        assert text.endswith("\n")
        keys = list(json.loads(text))
        assert keys == sorted(keys), lang


def test_fallback_to_en(monkeypatch):
    monkeypatch.setattr(i18n, "LANG", "nb")
    monkeypatch.setitem(i18n._load("en"), "only.en", "Hello {x}")
    assert i18n.t("only.en", x=1) == "Hello 1"
    with pytest.raises(KeyError):
        i18n.t("no.such.key")


def test_user_values_stay_literal():
    assert i18n.t_in("en", "banner.back", site="{site}") == "Back to {site}"
    assert str(i18n.t_html("login.sent", email="<b>x</b>", minutes=15)).count("&lt;b&gt;x&lt;/b&gt;") == 1


def test_lookup_follows_lang(monkeypatch):
    assert i18n.t("banner.back", site="X") == "Tilbake til X"
    monkeypatch.setattr(i18n, "LANG", "en")
    assert i18n.t("banner.back", site="X") == "Back to X"
    assert i18n.js("banner.") == {"back": "Back to {site}"}


def test_html_lang(client, english):
    assert '<html lang="en">' in client.get("/login").text


def test_html_lang_nb(client):
    assert '<html lang="nb">' in client.get("/login").text
