"""The strip at the top of every app page: "‹ [hub logo] | [app icon] App name", one link back to the front page.

It is a declarative shadow root (<template shadowrootmode>), so the app's CSS cannot reach inside it and its CSS
cannot leak into the app, and it works without JS. CSS_HOST goes in <head> and styles the host element itself,
which the app's CSS can still match (e.g. `* { ... }`). It resets the host with all:initial !important, and an
!important rule from the page also beats :host rules inside the shadow root, so the host's whole look lives here.

The server puts it right after <body>. A small script right behind it then moves it out of <body> (so a flex/grid
body or body margins cannot move it), makes it position:fixed at the top (data-fixed), and puts an empty
<hub-banner-space> after it that holds its place in the flow. The space is pulled up over any space above it (e.g.
:root safe-area padding, which the banner has itself). The banner's height is published as --hub-banner-h on :root,
so an app's own sticky bar can sit right under it. Without JS it simply stays in the flow where the server put it.
"""
from __future__ import annotations

import re
from html import escape

from app import i18n

CSS_HOST = (
    "<style>hub-banner{all:initial !important;display:block !important;position:relative !important;"
    "z-index:20 !important;"
    # full width even when the app pads <body>
    "margin:0 calc(50% - 50vw) !important;"
    "padding-top:env(safe-area-inset-top) !important;color:#f3f6fb !important;"
    "font:600 14px/1.2 ui-sans-serif,system-ui,-apple-system,'Segoe UI',sans-serif !important;"
    "-webkit-text-size-adjust:100% !important;"
    "background:radial-gradient(500px 120px at 90% -60%,rgb(255 138 92 / .22),transparent 60%),"
    "linear-gradient(160deg,#0b1a33,#123566) !important}"
    # fixed at the top once the script has run (data-fixed); without JS it stays in the flow
    "hub-banner[data-fixed]{position:fixed !important;top:0 !important;left:0 !important;right:0 !important;"
    "margin:0 !important}"
    # empty stand-in in the flow, as tall as the fixed banner
    "hub-banner-space{display:block;height:var(--hub-banner-h,0px)}"
    # The background is !important and cannot be animated, so the glow is an overlay (opacity only, no layout).
    # pull.js sets data-glow="ok"|"fail" for a moment.
    "hub-banner::after{content:'';position:absolute;inset:0;opacity:0;pointer-events:none}"
    "hub-banner[data-glow=\"ok\"]::after{background:#3fd39c;animation:hub-glow 900ms ease-out}"
    "hub-banner[data-glow=\"fail\"]::after{background:#e5484d;animation:hub-glow 900ms ease-out}"
    "@keyframes hub-glow{0%{opacity:0}30%{opacity:.35}100%{opacity:0}}"
    "@media print{hub-banner,hub-banner-space{display:none !important}}</style>"
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


_PLACE = (
    "<script>(function(s){var b=s.previousElementSibling,h=document.documentElement;s.remove();"
    "if(!b||b.localName!=='hub-banner'||b.parentNode!==document.body)return;h.insertBefore(b,document.body);"
    "var p=document.createElement('hub-banner-space');b.after(p);b.setAttribute('data-fixed','');"
    "function size(){h.style.setProperty('--hub-banner-h',b.offsetHeight+'px')}size();"
    "if(window.ResizeObserver)new ResizeObserver(size).observe(b);"
    "function fit(){p.style.removeProperty('margin-top');var t=p.getBoundingClientRect().top+scrollY;"
    "if(t>0.5)p.style.setProperty('margin-top',-t+'px','important')}"
    "fit();addEventListener('resize',fit)})(document.currentScript)</script>"
)

_HEAD_TAG = re.compile(r"<head(?:\s[^>]*)?>", re.I)
# The first real <body> tag; comments and raw-text elements are matched too, so a "<body>" inside them is skipped.
_BODY_TAG = re.compile(r"<!--.*?-->|<(script|style|title|textarea)\b.*?</\1\s*>|<body\b[^>]*>", re.I | re.S)


def inject(html: str, head: str, banner: str | None) -> str:
    """Put `head` right after <head> (or first), and `banner` right after the first real <body> tag
    (or right after `head` when there is none)."""
    m = _HEAD_TAG.search(html)
    at = m.end() if m else 0
    html = html[:at] + head + html[at:]
    if not banner:
        return html
    after_head = at + len(head)
    body = next((b for b in _BODY_TAG.finditer(html, after_head) if b.group().lower().startswith("<body")), None)
    at = body.end() if body else after_head
    return html[:at] + banner + _PLACE + html[at:]


def render(app: dict, site: str) -> str:
    """The banner for one app (an entry from list_artifacts), linking to the front page of `site`."""
    label = escape(i18n.t("banner.back", site=site))
    return (
        f'<hub-banner><template shadowrootmode="open">{_STYLE}'
        f'<a href="/" aria-label="{label}" title="{label}">'
        '<span class="back" aria-hidden="true">‹</span>'
        '<img class="hub" src="/static/logo.svg" alt="" width="18" height="18">'
        '<span class="sep"></span>'
        f'{_icon(app)}<span class="name">{escape(app.get("title") or "")}</span>'
        "</a></template></hub-banner>"
    )
