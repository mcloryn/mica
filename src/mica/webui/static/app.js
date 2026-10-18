// UI kiosk MICA (Langkah 37): merender JSON ViewModel dari server dan mengirim event input.
// Tidak ada logika state di sini; aturan event diperiksa lagi di server (mica.webui.state).
// Tidak ada timer atau animasi JS: gerak hanya lewat CSS saat status aktif.
"use strict";

const $ = (id) => document.getElementById(id);
const ws = new WebSocket(`ws://${location.host}/ws`);
let config = null;
let view = null;
let rendered = 0; // jumlah pesan yang sudah menjadi elemen
let shownTranscript = null;

function send(msg) {
  if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
}

function el(tag, className, text) {
  const e = document.createElement(tag);
  if (className) e.className = className;
  if (text !== undefined) e.textContent = text;
  return e;
}

function fillQuestion(topic) {
  // kartu/chip topik HANYA mengisi kotak pertanyaan dengan nama topik (bukan pertanyaan set uji)
  const input = $("input");
  input.value = `${topic} `;
  input.focus();
  input.setSelectionRange(input.value.length, input.value.length);
}

function topicButton(topic, className) {
  const b = el("button", className, topic);
  b.type = "button";
  b.addEventListener("click", () => fillQuestion(topic));
  return b;
}

function applyConfig(c) {
  config = c;
  document.documentElement.style.fontSize = `${125 * c.font_scale}%`;
  const t = c.texts;
  $("app_title").textContent = t.app_title;
  $("topics_hint").textContent = t.topics_hint;
  $("input").placeholder = t.input_placeholder;
  $("send_button").textContent = t.send;
  $("talk_button").setAttribute("aria-label", t.talk);
  $("stop_button").textContent = t.stop;
  $("resend_button").textContent = t.resend;
  $("transcript_label").textContent = t.transcript_label;
  if (c.logo) {
    $("logo_img").src = c.logo;
    $("logo_img").hidden = false;
    $("logo_text").hidden = true;
  }
  $("topic_cards").replaceChildren(...c.topics.map((x) => topicButton(x.topic, "topic-card")));
  $("chips").replaceChildren(...c.topics.map((x) => topicButton(x.topic, "chip")));
  $("debug_dock").hidden = !c.dev;
}

function messageElement(m) {
  if (m.kind === "visitor") return el("div", "bubble visitor", m.text);
  const box = el("div", m.kind === "answer" ? "card-answer" : "card-notice");
  box.append(el("div", "who", m.who), el("div", "text", m.text));
  if (m.sources.length) {
    const src = el("div", "sources");
    src.textContent = `${config.texts.sources_label} ${m.sources.join("; ")}`;
    box.append(src);
  }
  return box;
}

function indicator(id, ok, onLabel, offLabel) {
  const node = $(id);
  node.classList.toggle("off", !ok);
  node.querySelector(".label").textContent = ok ? onLabel : offLabel;
}

function renderLeft(v) {
  const t = config.texts;
  const target = $("target_text");
  const dot = $("target_dot");
  const msg = $("camera_message");
  if (!v.camera_ok) {
    target.textContent = "";
    dot.hidden = true;
    msg.textContent = t.camera_unavailable; // N-10
  } else if (v.target_present) {
    const color = v.target_color ? ` ${v.target_color[0].toUpperCase()}${v.target_color.slice(1)}` : "";
    target.textContent = `${t.target_label}:${color} · ${t.target_locked}`;
    dot.hidden = !v.target_swatch;
    if (v.target_swatch) dot.style.background = v.target_swatch;
    msg.textContent = "";
  } else {
    target.textContent = "";
    dot.hidden = true;
    msg.textContent = t.approach;
  }
}

function render(v) {
  view = v;
  document.body.dataset.status = v.pill;
  $("status_pill").textContent = v.pill_label;
  $("notice").textContent = v.notice; // N-08: selalu tampil
  indicator("camera_indicator", v.camera_ok, config.texts.camera_on, config.texts.camera_off);
  indicator("mic_indicator", v.mic_ok, config.texts.mic_on, config.texts.mic_off);
  $("talk_button").disabled = !v.talk_enabled;
  $("send_button").disabled = !v.send_enabled;
  $("resend_button").disabled = !v.send_enabled;
  $("stop_button").hidden = v.pill !== "speaking";
  $("greeting").textContent = v.greeting;
  renderLeft(v);
  const conv = $("conversation");
  if (rendered > v.messages.length) { // ClearScreen
    conv.replaceChildren();
    rendered = 0;
  }
  for (const m of v.messages.slice(rendered)) conv.append(messageElement(m));
  rendered = v.messages.length;
  $("home").hidden = !v.home;
  conv.hidden = v.home;
  $("chips").hidden = v.home; // kartu menyusut jadi chip setelah percakapan mulai
  $("transcript_row").hidden = v.last_transcript === null;
  if (v.last_transcript !== shownTranscript) { // suntingan pengunjung tidak ditimpa
    $("transcript_edit").value = v.last_transcript || "";
    shownTranscript = v.last_transcript;
  }
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
  else if (msg.type === "view") {
    render(msg.view);
    // dilaporkan setelah requestAnimationFrame berikutnya (jeda tampil diukur di Python)
    requestAnimationFrame(() => send({ type: "ack", seq: msg.seq }));
  }
});

$("input").addEventListener("keydown", (e) => {
  if (e.key === "Enter") submitText($("input"), "text");
});
$("send_button").addEventListener("click", () => submitText($("input"), "text"));
$("resend_button").addEventListener("click", () => submitText($("transcript_edit"), "resend"));
$("talk_button").addEventListener("click", () => send({ type: "talk" }));
$("stop_button").addEventListener("click", () => send({ type: "stop" }));
