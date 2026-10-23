import io
import zipfile

import pytest

from app import banner

APP = {"title": "Matboka", "emoji": "🥗", "icon_url": None, "hue": 120}


# ---------------------------------------------------------------- markup
def test_links_home_with_label():
    out = banner.render(APP, "Innovolt apps")
    assert out.startswith("<hub-banner>") and 'shadowrootmode="open"' in out
    assert 'href="/"' in out and 'aria-label="Tilbake til Innovolt apps"' in out
    assert "history.back" not in out and "<script" not in out


def test_emoji_sits_before_name():
    out = banner.render(APP, "S")
    assert out.index("🥗") < out.index("Matboka")


def test_image_icon_and_letter_fallback():
    assert '<img src="/icon/x?v=1"' in banner.render({**APP, "icon_url": "/icon/x?v=1"}, "S")
    out = banner.render({**APP, "emoji": ""}, "S")
    assert ">M<" in out and "hsl(120" in out


def test_title_and_site_escaped():
    out = banner.render({**APP, "title": '<script>x</script>"&'}, 'A"B')
    assert "<script>x" not in out and "&lt;script&gt;" in out and "&amp;" in out
    assert "Tilbake til A&quot;B" in out


def test_one_line_and_print_hidden():
    out = banner.render(APP, "S")
    assert "white-space:nowrap" in out.replace(" ", "") and "ellipsis" in out
    assert "safe-area-inset-top" in out
    assert "@media print" in banner.CSS_HOST
