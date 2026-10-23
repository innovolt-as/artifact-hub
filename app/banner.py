"""The strip at the top of every app page: "‹ [hub logo] | [app icon] App name", one link back to the front page.

It is a declarative shadow root (<template shadowrootmode>), so the app's CSS cannot reach inside it and its CSS
cannot leak into the app, and it works without JS. CSS_HOST goes in <head> and guards the host element itself,
which the app's CSS can still match (e.g. `* { ... }`); !important from outside beats the app's normal rules.
"""
from __future__ import annotations

from html import escape

CSS_HOST = (
    "<style>hub-banner{all:initial !important;display:block !important;position:relative !important;"
    "z-index:20 !important}@media print{hub-banner{display:none !important}}</style>"
)

_STYLE = """<style>
:host{display:block;color:#f3f6fb;font:600 14px/1.2 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;
  padding-top:env(safe-area-inset-top);-webkit-text-size-adjust:100%;
  background:radial-gradient(500px 120px at 90% -60%,rgb(255 138 92 / .22),transparent 60%),
             linear-gradient(160deg,#0b1a33,#123566)}
a{display:flex;align-items:center;gap:8px;min-width:0;min-height:22px;padding:10px 16px;color:inherit;
  text-decoration:none;white-space:nowrap;-webkit-tap-highlight-color:transparent}
a:focus-visible{outline:2px solid #cfe0ff;outline-offset:-4px;border-radius:8px}
.back{flex:none;font-size:20px;line-height:1;color:#cfe0ff;margin-top:-2px}
.hub,.ico{flex:none;display:block;width:18px;height:18px}
.sep{flex:none;width:1px;height:14px;background:rgb(255 255 255 / .25)}
.ico{display:grid;place-items:center;font-size:16px;line-height:1}
.ico img{width:18px;height:18px;border-radius:5px;object-fit:cover}
.ico.letter{border-radius:5px;font-size:11px;font-weight:700;color:#fff}
.name{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
</style>"""


def _icon(app: dict) -> str:
    """Same order as the front page (_icon.html): uploaded image, else emoji, else the first letter."""
    if app.get("icon_url"):
        return f'<span class="ico"><img src="{escape(app["icon_url"])}" alt=""></span>'
    if app.get("emoji"):
        return f'<span class="ico">{escape(app["emoji"])}</span>'
    letter = escape((app.get("title") or "?")[:1].upper())
    return f'<span class="ico letter" style="background:hsl({int(app.get("hue", 0))} 55% 45%)">{letter}</span>'


def render(app: dict, site: str) -> str:
    """The banner for one app (an entry from list_artifacts), linking to the front page of `site`."""
    label = escape(f"Tilbake til {site}")
    return (
        f'<hub-banner><template shadowrootmode="open">{_STYLE}'
        f'<a href="/" aria-label="{label}" title="{label}">'
        '<span class="back" aria-hidden="true">‹</span>'
        '<img class="hub" src="/static/logo.svg" alt="" width="18" height="18">'
        '<span class="sep"></span>'
        f'{_icon(app)}<span class="name">{escape(app.get("title") or "")}</span>'
        "</a></template></hub-banner>"
    )
