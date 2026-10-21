"""Kontrak index.html <-> app.js (Langkah 57): tampilan boleh berganti, id dan skrip tidak.

Daftar id beserta jenis elemennya dibekukan dari index.html sebelum versi F (commit f3486ec).
Elemen tampilan tanpa id boleh ditambah; id, jenis elemen, atribut hidden awal, template ikon,
dan urutan skrip tidak boleh berubah tanpa mengubah app.js.
"""

import hashlib
import re
from html.parser import HTMLParser

from mica.webui.server import STATIC_DIR

CONTRACT = {
    "navbar": "header", "brand": "div", "logo_text": "span", "logo_img": "img",
    "app_title": "span", "trial_badge": "span", "prompt_badge": "span", "indicators": "div",
    "camera_indicator": "span", "mic_indicator": "span", "layout": "main", "left": "section",
    "camera_title": "h2", "preview_frame": "div", "preview_img": "img", "preview_empty": "div",
    "color_info": "div", "swatch_big": "span", "color_text": "p", "camera_info": "p",
    "debug_dock": "details", "debug_panel": "pre", "right": "section", "conversation": "div",
    "welcome": "div", "welcome_title": "h1", "welcome_greeting": "p", "topics_hint": "p",
    "topic_grid": "div", "greeting_msg": "div", "greeting": "p", "messages": "div",
    "chips": "div", "status_line": "p", "status_icon": "span", "status_text": "span",
    "transcript_row": "div", "transcript_label": "label", "transcript_edit": "input",
    "resend_button": "button", "bottom_bar": "div", "talk_button": "button",
    "talk_label": "span", "input": "input", "send_button": "button", "stop_button": "button",
    "footer": "footer", "notice": "p", "icon-info": "template", "icon-doc": "template",
    "icon-listening": "template", "icon-thinking": "template", "icon-speaking": "template",
    "icon-ready": "template", "icon-topic": "template", "icon-topic-program-studi": "template",
    "icon-topic-biaya": "template", "icon-topic-beasiswa": "template",
    "icon-topic-pendaftaran": "template", "icon-topic-fasilitas": "template",
    "icon-topic-lokasi": "template", "measure_panel": "pre", "guide_box": "pre",
}  # fmt: skip
HIDDEN_AT_START = {"logo_img", "trial_badge", "prompt_badge", "preview_img", "swatch_big",
                   "debug_dock", "greeting_msg", "chips", "transcript_row", "stop_button",
                   "measure_panel", "guide_box"}  # fmt: skip
# sha256 baris <template id="icon-..."> di index.html f3486ec (ikon garis lokal)
TEMPLATES_SHA256 = "bcd9afe1a8b8ed7953e1b26b4d0258ef31be80487f06295d0f8c6d3fd8e4e170"


class _Ids(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.elements: list[tuple[str, str, dict]] = []
        self.scripts: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a:
            self.elements.append((a["id"], tag, a))
        if tag == "script":
            self.scripts.append(a.get("src", ""))


def _page():
    html = (STATIC_DIR / "index.html").read_text("utf-8")
    p = _Ids()
    p.feed(html)
    return html, p


def test_ids_and_element_types_match_contract():
    _, p = _page()
    ids = [i for i, _, _ in p.elements]
    assert len(ids) == len(set(ids)), "id ganda"
    assert {i: t for i, t, _ in p.elements} == CONTRACT


def test_hidden_at_start_unchanged():
    _, p = _page()
    assert {i for i, _, a in p.elements if "hidden" in a} == HIDDEN_AT_START


def test_icon_templates_unchanged():
    html, _ = _page()
    lines = [ln for ln in html.splitlines() if ln.startswith('<template id="icon-')]
    digest = hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()
    assert digest == TEMPLATES_SHA256


def test_script_order_answer_format_then_app():
    _, p = _page()
    assert p.scripts == ["/static/answer_format.js", "/static/app.js"]


def test_every_id_used_by_app_js_exists():
    js = (STATIC_DIR / "app.js").read_text("utf-8")
    used = set(re.findall(r'\$\("([\w-]+)"\)', js))
    assert used and used <= set(CONTRACT)
    statuses = ("listening", "thinking", "speaking", "ready")
    assert {f"icon-{s}" for s in statuses} | {"icon-info", "icon-doc"} <= set(CONTRACT)
