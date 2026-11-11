"""static/admin-chips.js (the choice of collection names in the admin sheet), run in V8 (py_mini_racer): the pure functions
behind the buttons, with no DOM."""
import json
from pathlib import Path

from py_mini_racer import MiniRacer

CHIPS_JS = (Path(__file__).resolve().parent.parent / "app" / "static" / "admin-chips.js").read_text(encoding="utf-8")


def run(expr):
    ctx = MiniRacer()
    ctx.eval("globalThis.window = globalThis;" + CHIPS_JS)
    return json.loads(ctx.eval(f"JSON.stringify({expr})"))


def chip(name, on=False, disabled=False):
    return {"name": name, "on": on, "disabled": disabled}


def test_chips_are_every_existing_name_and_every_selected_one_sorted():
    got = run("AdminChips.chips(['tips', 'products'], ['zebra', 'tips'], [])")
    assert got == [chip("products"), chip("tips", on=True), chip("zebra", on=True)]


def test_no_collections_and_nothing_selected_gives_no_chips():
    assert run("AdminChips.chips([], [], [])") == []


def test_a_name_in_the_other_setting_is_a_disabled_chip_only_when_it_exists():
    got = run("AdminChips.chips(['a', 'b'], [], ['b', 'ghost'])")
    assert got == [chip("a"), chip("b", disabled=True)]


def test_a_selected_name_is_never_disabled():
    assert run("AdminChips.chips(['a'], ['a'], ['a'])") == [chip("a", on=True)]


def test_press_adds_and_removes_and_keeps_the_order():
    assert run("AdminChips.press(['a'], 'b')") == ["a", "b"]
    assert run("AdminChips.press(['a', 'b', 'c'], 'b')") == ["a", "c"]
    assert run("AdminChips.press([], 'a')") == ["a"]


def test_press_does_not_change_its_argument():
    assert run("(() => { const s = ['a']; AdminChips.press(s, 'b'); return s; })()") == ["a"]


def test_typed_name_becomes_selected():
    got = run("AdminChips.typed(['a'], '  queue ', [])")
    assert got == {"selected": ["a", "queue"], "refused": []}


def test_typed_names_may_be_comma_separated_and_repeats_are_ignored():
    got = run("AdminChips.typed(['a'], 'b, a,, c ,b', [])")
    assert got == {"selected": ["a", "b", "c"], "refused": []}


def test_typed_empty_text_changes_nothing():
    assert run("AdminChips.typed(['a'], '   ', [])") == {"selected": ["a"], "refused": []}


def test_typed_bad_and_taken_names_are_refused_with_a_reason_and_the_rest_kept():
    got = run("AdminChips.typed([], 'ok, bad name, data, mine, ' + 'x'.repeat(65), ['mine'])")
    assert got["selected"] == ["ok"]
    assert got["refused"] == [{"name": "bad name", "why": "bad"}, {"name": "data", "why": "bad"},
                              {"name": "mine", "why": "other"}, {"name": "x" * 65, "why": "bad"}]
