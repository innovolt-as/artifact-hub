"""The strip at the top of every app page: "‹ [hub logo] | [app icon] App name", one link back to the front page.

It is a declarative shadow root (<template shadowrootmode>), so the app's CSS cannot reach inside it and its CSS
cannot leak into the app, and it works without JS. CSS_HOST goes in <head> and styles the host element itself,
which the app's CSS can still match (e.g. `* { ... }`). It resets the host with all:initial !important, and an
!important rule from the page also beats :host rules inside the shadow root, so the host's whole look lives here.
"""
from __future__ import annotations

from html import escape

CSS_HOST = (
    "<style>hub-banner{all:initial !important;display:block !important;position:relative !important;"
    "z-index:20 !important;"
    # full width even when the app pads <body> (e.g. Lommeomregner)
    "margin:0 calc(50% - 50vw) !important;"
    "padding-top:env(safe-area-inset-top) !important;color:#f3f6fb !important;"
    "font:600 14px/1.2 ui-sans-serif,system-ui,-apple-system,'Segoe UI',sans-serif !important;"
    "-webkit-text-size-adjust:100% !important;"
    "background:radial-gradient(500px 120px at 90% -60%,rgb(255 138 92 / .22),transparent 60%),"
    "linear-gradient(160deg,#0b1a33,#123566) !important}"
    "@media print{hub-banner{display:none !important}}</style>"
)

_STYLE = """<style>
a{display:flex;align-items:center;gap:8px;min-width:0;min-height:22px;padding:10px 16px;color:inherit;
  text-decoration:none;white-space:nowrap;-webkit-tap-highlight-color:transparent}
a:focus-visible{outline:2px solid #cfe0ff;outline-offset:-4px;border-radius:8px}
.back{flex:none;font-size:20px;line-height:1;color:#cfe0ff;margin-top:-2px}
.hub{flex:none;display:block;width:18px;height:18px}
.sep{flex:none;width:1px;height:14px;background:rgb(255 255 255 / .25)}
.ico{flex:none;display:grid;place-items:center;min-width:18px;height:18px;font-size:16px;line-height:1}
.ico img{width:18px;height:18px;border-radius:5px;object-fit:cover}
.ico.letter{width:18px;border-radius:5px;font-size:11px;font-weight:700;color:#fff}
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
