// UI kiosk MICA (Langkah 37c): merender JSON ViewModel dari server dan mengirim event input.
// Tidak ada logika state di sini; aturan event diperiksa lagi di server (mica.webui.state).
// Tidak ada timer atau animasi JS. Warna sesi diberikan lewat body[data-color] (tokens.css).
"use strict";

const $ = (id) => document.getElementById(id);
const ws = new WebSocket(`ws://${location.host}/ws`);
let config = null;
let view = null;
let rendered = 0; // jumlah pesan yang sudah menjadi elemen
let shownTranscript = null;
let shownStatus = null;
let previewSocket = null;
let previewUrl = null;

function send(msg) {
  if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
}

function el(tag, className, text) {
  const e = document.createElement(tag);
  if (className) e.className = className;
  if (text !== undefined) e.textContent = text;
  return e;
}

function icon(name) {
  // ikon garis dari <template id="icon-..."> di index.html (SVG lokal, satu gaya)
  const t = $(`icon-${name}`) || $("icon-topic");
  return t.content.firstElementChild.cloneNode(true);
}

const slug = (text) => text.toLowerCase().replace(/\s+/g, "-");

function fillQuestion(topic) {
  // topik HANYA mengisi kotak pertanyaan dengan nama topik (bukan pertanyaan set uji)
  const input = $("input");
  input.value = `${topic} `;
  input.focus();
  input.setSelectionRange(input.value.length, input.value.length);
}

function topicButton(topic, tile) {
  const b = el("button", tile ? "topic-tile" : "btn btn-topic");
  b.type = "button";
  if (tile) b.append(icon(`topic-${slug(topic)}`));
  b.append(el("span", "", topic));
  b.addEventListener("click", () => fillQuestion(topic));
  return b;
}

function applyConfig(c) {
  config = c;
  document.documentElement.style.fontSize = `${100 * c.font_scale}%`;
  const t = c.texts;
  $("app_title").textContent = t.app_title;
  $("welcome_title").textContent = t.welcome_title;
  $("topics_hint").textContent = t.topics_hint;
  $("camera_title").textContent = t.camera_title;
  $("camera_info").textContent = t.camera_info;
  $("input").placeholder = t.input_placeholder;
  $("send_button").textContent = t.send;
  $("stop_button").textContent = t.stop;
  $("resend_button").textContent = t.resend;
  $("transcript_label").textContent = t.transcript_label;
  if (c.logo) {
    $("logo_img").src = c.logo;
    $("logo_img").hidden = false;
    $("logo_text").hidden = true;
  }
  $("topic_grid").replaceChildren(...c.topics.map((x) => topicButton(x.topic, true)));
  $("chips").replaceChildren(...c.topics.map((x) => topicButton(x.topic, false)));
  $("debug_dock").hidden = !c.dev;
  $("trial_badge").textContent = t.trial_badge;
  $("trial_badge").hidden = !c.trial; // --trial-values (Langkah 41)
  $("prompt_badge").textContent = c.prompt_badge || "";
  $("prompt_badge").hidden = !c.prompt_badge; // --prompt-variant (dev saja)
  if (c.preview !== "off" && previewSocket === null) openPreview();
  if (c.measure && c.dev) startPreviewMeter();
}

function startPreviewMeter() {
  // hanya dev (--measure-preview): setiap gambar pratinjau yang dimuat dilaporkan langsung
  // beserta jeda sejak gambar sebelumnya (ms), tanpa timer; tanpa gambar
  let last = null;
  $("preview_img").addEventListener("load", () => {
    const now = performance.now();
    send({ type: "preview_drawn", n: 1, gap_ms: last === null ? null : Math.round(now - last) });
    last = now;
  });
}

function renderGuide(g) {
  // --guided-test (dev): langkah sekarang, hitung mundur, langkah berikutnya
  if (!config || !config.dev || !config.guided) return;
  const lines = [g.step ? `Langkah ${g.step}/${g.steps}: ${g.text}` : g.text];
  if (g.remaining_s !== null) {
    const m = Math.floor(g.remaining_s / 60);
    const s = String(g.remaining_s % 60).padStart(2, "0");
    lines.push(`Sisa ${m}:${s}`);
  }
  if (g.next) lines.push(`Berikutnya: ${g.next}`);
  $("guide_box").textContent = lines.join("\n");
  $("guide_box").hidden = false;
}

function openPreview() {
  // pratinjau kamera: JPEG biner dari /preview (127.0.0.1, Origin dicek server); hanya di memori
  previewSocket = new WebSocket(`ws://${location.host}/preview`);
  previewSocket.binaryType = "blob";
  previewSocket.addEventListener("open", () => { window.__micaPreviewReady = true; });
  previewSocket.addEventListener("message", (e) => {
    const img = $("preview_img");
    const old = previewUrl;
    previewUrl = URL.createObjectURL(e.data);
    img.src = previewUrl;
    if (old) URL.revokeObjectURL(old);
    if (view === null || view.camera_ok) {
      img.hidden = false;
      $("preview_empty").hidden = true;
    }
  });
}

function renderMeasure(r) {
  // --measure-preview (dev): angka per detik di pojok; tanpa gambar
  if (!config || !config.dev || !config.measure) return;
  const f = (x) => (x === null || x === undefined ? "-" : String(x));
  const c = r.cpu_pct;
  $("measure_panel").textContent = [
    `status ${r.status}`,
    `tangkap ${f(r.capture_fps)} | kirim ${f(r.server_sent_fps)} | gambar ${f(r.browser_drawn_fps)} fps`,
    `CPU utama ${f(c.utama)} vision ${f(c.vision)} suara ${f(c.suara)} total ${f(c.total_machine)}%`,
  ].join("\n");
  $("measure_panel").hidden = false;
}

function answerBlocks(text) {
  // hanya createElement/textContent; teks LLM tidak pernah diurai sebagai HTML
  return window.MicaAnswerFormat.formatAnswer(text).map((b) => {
    if (b.type === "p") return el("p", "", b.text);
    const list = el(b.type); // ol (bernomor) atau ul (baris "- ", prompt v3)
    if (b.type === "ol" && b.start !== 1) list.start = b.start;
    list.append(...b.items.map((x) => el("li", "", x)));
    return list;
  });
}

function messageElement(m) {
  const box = el("div", `msg ${m.kind === "visitor" ? "visitor" : "mica"}`);
  box.append(el("div", "who", m.who));
  const bubble = el("div", "bubble");
  if (m.kind === "notice") { // penolakan: gelembung MICA biasa dengan ikon info kecil
    const line = el("div", "notice-line");
    line.append(icon("info"), el("span", "", m.text));
    bubble.append(line);
  } else if (m.kind === "visitor") {
    bubble.textContent = m.text;
  } else { // jawaban: paragraf/daftar dari answer_format.js (tampilan saja; m.text tetap utuh)
    bubble.classList.add("answer");
    bubble.append(...answerBlocks(m.text));
    if (m.items.length) { // prompt v4: items -> <ul> (textContent)
      const list = el("ul", "answer-items");
      list.append(...m.items.map((x) => el("li", "", x)));
      bubble.append(list);
    }
  }
  box.append(bubble);
  if (m.sources.length) {
    const src = el("div", "sources");
    src.append(icon("doc"), el("span", "", `${config.texts.sources_label} ${m.sources.join("; ")}`));
    box.append(src);
  }
  if (m.follow_up) { // prompt v3: tawaran topik lanjutan; tombol = chip topik (mengisi kotak)
    const offer = el("div", "follow-up");
    offer.append(el("span", "", m.follow_up.text), topicButton(m.follow_up.topic, false));
    box.append(offer);
  }
  return box;
}

function indicator(id, ok, label) {
  const node = $(id);
  node.classList.toggle("off", !ok);
  node.querySelector(".label").textContent = label; // termasuk "Menyiapkan ..." (Langkah 40)
}

function renderLeft(v) {
  const t = config.texts;
  const text = $("color_text");
  const swatch = $("swatch_big");
  if (v.camera_starting) { // Langkah 40: kamera belum melapor
    swatch.hidden = true;
    text.textContent = v.camera_label;
    text.className = "quiet";
  } else if (!v.camera_ok) {
    swatch.hidden = true;
    text.textContent = t.camera_unavailable; // N-10
    text.className = "quiet";
    $("preview_img").hidden = true; // gambar terakhir tidak ditampilkan saat kamera mati
    $("preview_empty").hidden = false;
  } else if (v.target_present) {
    swatch.hidden = !v.session_color; // memudar masuk 200 ms (CSS) saat muncul
    text.textContent = v.target_color ? t.wearing.replace("{warna}", v.target_color) : t.detected_no_color;
    text.className = "";
  } else {
    swatch.hidden = true;
    text.textContent = t.approach;
    text.className = "quiet";
  }
}

function renderStatus(v) {
  const key = `${v.pill}|${v.status_line}`; // kalimat bisa berubah dalam status yang sama
  if (key === shownStatus) return;
  shownStatus = key;
  $("status_icon").replaceChildren(icon(v.pill));
  $("status_text").textContent = v.status_line;
}

function render(v) {
  view = v;
  const t = config.texts;
  document.body.dataset.status = v.pill;
  if (v.session_color) document.body.dataset.color = v.session_color;
  else delete document.body.dataset.color; // sesi selesai/reset: kembali netral
  $("notice").textContent = v.notice; // N-08: selalu tampil
  indicator("camera_indicator", v.camera_ok, v.camera_label);
  indicator("mic_indicator", v.mic_ok, v.mic_label);
  const talk = $("talk_button");
  talk.disabled = !v.talk_enabled;
  talk.classList.toggle("btn-primary", v.talk_enabled);
  $("talk_label").textContent = v.talk_enabled ? t.talk
    : v.mic_starting ? v.mic_label : t.mic_unavailable_button;
  $("send_button").classList.toggle("btn-primary", !v.talk_enabled); // utama bila tanpa mic
  $("send_button").disabled = !v.send_enabled;
  $("resend_button").disabled = !v.send_enabled;
  $("stop_button").hidden = v.pill !== "speaking";
  $("welcome_greeting").textContent = v.greeting;
  $("greeting").textContent = v.greeting;
  $("welcome").hidden = !v.home;
  $("greeting_msg").hidden = v.home; // setelah mulai, sapaan jadi pesan pertama
  $("chips").hidden = v.home; // grid topik menyusut jadi satu baris tombol kecil
  renderLeft(v);
  renderStatus(v);
  const list = $("messages");
  if (rendered > v.messages.length) { // ClearScreen
    list.replaceChildren();
    rendered = 0;
  }
  for (const m of v.messages.slice(rendered)) list.append(messageElement(m));
  rendered = v.messages.length;
  $("transcript_row").hidden = v.last_transcript === null;
  if (v.last_transcript !== shownTranscript) { // suntingan pengunjung tidak ditimpa
    $("transcript_edit").value = v.last_transcript || "";
    shownTranscript = v.last_transcript;
  }
  const conv = $("conversation");
  conv.scrollTop = conv.scrollHeight; // gulir otomatis ke pesan terakhir
}

function submitText(input, type) {
  const text = input.value.trim();
  if (text && view && view.send_enabled) {
    send({ type, text });
    if (type === "text") input.value = "";
  }
}

ws.addEventListener("message", (e) => {
  const msg = JSON.parse(e.data);
  if (msg.type === "config") applyConfig(msg);
  else if (msg.type === "debug") $("debug_panel").textContent = msg.text;
  else if (msg.type === "measure") renderMeasure(msg.row);
  else if (msg.type === "guide") renderGuide(msg);
  else if (msg.type === "view") {
    render(msg.view);
    // dilaporkan setelah requestAnimationFrame berikutnya (jeda tampil diukur di Python)
    requestAnimationFrame(() => send({ type: "ack", seq: msg.seq }));
  }
});

// Langkah 51: tanda "sedang mengetik" (tanpa isi teks) paling sering sekali per 500 ms, supaya
// sesi tidak berakhir saat pengunjung menunduk ke keyboard
let typingSent = 0;
function noteTyping() {
  const now = performance.now();
  if (now - typingSent >= 500) {
    send({ type: "typing" });
    typingSent = now;
  }
}
$("input").addEventListener("input", noteTyping);
$("transcript_edit").addEventListener("input", noteTyping);

$("input").addEventListener("keydown", (e) => {
  if (e.key === "Enter") submitText($("input"), "text");
});
$("send_button").addEventListener("click", () => submitText($("input"), "text"));
$("resend_button").addEventListener("click", () => submitText($("transcript_edit"), "resend"));
// Bicara. audio.input_mode push_to_talk (Langkah 42): tahan untuk merekam, lepas untuk mengirim;
// pointer keluar dari tombol atau pointercancel = dibatalkan. Spasi (dev) saat fokus bukan di
// kotak ketik. Mode vad (lama): klik sekali.
let talkHeld = false;

function talkPress() {
  if (talkHeld || $("talk_button").disabled) return;
  talkHeld = true;
  $("talk_button").classList.add("held");
  send({ type: "talk_press" });
}

function talkEnd(type) {
  if (!talkHeld) return;
  talkHeld = false;
  $("talk_button").classList.remove("held");
  send({ type });
}

function insideTalk(e) {
  const r = $("talk_button").getBoundingClientRect();
  return e.clientX >= r.left && e.clientX <= r.right && e.clientY >= r.top && e.clientY <= r.bottom;
}

const talkButton = $("talk_button");
talkButton.addEventListener("click", () => {
  if (config && config.input_mode !== "push_to_talk") send({ type: "talk" });
});
talkButton.addEventListener("pointerdown", (e) => {
  if (!config || config.input_mode !== "push_to_talk" || e.button > 0) return;
  e.preventDefault();
  talkButton.setPointerCapture(e.pointerId);
  talkPress();
});
talkButton.addEventListener("pointermove", (e) => {
  if (talkHeld && !insideTalk(e)) talkEnd("talk_cancel"); // keluar dari tombol
});
talkButton.addEventListener("pointerup", (e) => talkEnd(insideTalk(e) ? "talk_release" : "talk_cancel"));
talkButton.addEventListener("pointercancel", () => talkEnd("talk_cancel"));
talkButton.addEventListener("contextmenu", (e) => e.preventDefault()); // tekan lama di layar sentuh

function typingTarget(el) {
  return el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable);
}

document.addEventListener("keydown", (e) => {
  if (e.code !== "Space" || !config || config.input_mode !== "push_to_talk") return;
  if (typingTarget(document.activeElement)) return;
  e.preventDefault();
  if (!e.repeat) talkPress();
});
document.addEventListener("keyup", (e) => {
  if (e.code !== "Space" || typingTarget(document.activeElement)) return;
  e.preventDefault();
  talkEnd("talk_release");
});
window.addEventListener("blur", () => talkEnd("talk_cancel")); // jendela kehilangan fokus
$("stop_button").addEventListener("click", () => send({ type: "stop" }));
