// UI web MICA (percobaan ADR-19): merender JSON ViewModel dari server dan mengirim event input.
// Tidak ada logika state di sini; aturan event diperiksa lagi di server (mica.webui.state).
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

function button(label, onClick) {
  const b = document.createElement("button");
  b.type = "button";
  b.textContent = label;
  b.addEventListener("click", onClick);
  return b;
}

function applyConfig(c) {
  config = c;
  document.documentElement.style.fontSize = `${100 * c.font_scale}%`;
  const t = c.texts;
  $("home_title").textContent = t.home_title;
  $("input").placeholder = t.input_placeholder;
  $("send_button").textContent = t.send;
  $("talk_button").textContent = t.talk;
  $("stop_button").textContent = t.stop;
  $("resend_button").textContent = t.resend;
  $("transcript_label").textContent = t.transcript_label;
  $("notice").textContent = t.notice; // N-08: selalu tampil
  const topics = $("topics");
  topics.replaceChildren();
  for (const item of c.topics) {
    const col = document.createElement("div");
    col.className = "topic-col";
    const main = button(item.topic, () => send({ type: "topic", topic: item.topic, question: item.question }));
    main.className = "topic";
    col.append(main);
    for (const q of item.suggestions) {
      const hint = button(q, () => send({ type: "topic", topic: item.topic, question: q }));
      hint.className = "suggestion";
      col.append(hint);
    }
    topics.append(col);
  }
  $("debug_dock").hidden = !c.dev;
}

function messageElement(m) {
  const box = document.createElement("div");
  box.className = `message message_${m.role}`;
  const who = document.createElement("div");
  who.className = "who";
  who.textContent = m.who;
  const text = document.createElement("div");
  text.className = "text";
  text.textContent = m.text;
  box.append(who, text);
  if (m.sources.length) {
    const src = document.createElement("div");
    src.className = "sources";
    src.textContent = [config.texts.sources_label, ...m.sources.map((s) => `• ${s}`)].join("\n");
    box.append(src);
  }
  return box;
}

function render(v) {
  view = v;
  $("status").textContent = v.status_label;
  $("camera_indicator").textContent = v.camera_label;
  $("mic_indicator").textContent = v.mic_label;
  $("talk_button").disabled = !v.talk_enabled;
  $("send_button").disabled = !v.send_enabled;
  $("resend_button").disabled = !v.send_enabled;
  const conv = $("conversation");
  if (rendered > v.messages.length) { // ClearScreen
    conv.replaceChildren();
    rendered = 0;
  }
  for (const m of v.messages.slice(rendered)) conv.append(messageElement(m));
  rendered = v.messages.length;
  $("home").hidden = !v.home;
  conv.hidden = v.home;
  $("transcript_row").hidden = v.last_transcript === null;
  if (v.last_transcript !== shownTranscript) { // suntingan pengunjung tidak ditimpa
    $("transcript_edit").value = v.last_transcript || "";
    shownTranscript = v.last_transcript;
  }
  conv.scrollTop = conv.scrollHeight; // gulir otomatis ke jawaban terakhir
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
