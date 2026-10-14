// Tampilan MICA: menampilkan dan mengucapkan sapaan, dan menerima pertanyaan lewat ketikan atau suara.

const IDLE_TIMEOUT_MS = 60000;    // 60 detik tanpa aktivitas: sesi ditutup, kembali ke tampilan awal
const MAX_RECORDING_MS = 15000;   // rekaman berhenti sendiri setelah 15 detik

// Warna kartu untuk tiap nama warna MICA. Dipilih mendekati warna kain, bukan warna layar murni.
const SWATCH_COLORS = {
  "hitam": "#1f2023", "putih": "#f7f7f4", "abu-abu": "#8e918f", "merah": "#c8302b",
  "oranye": "#e57a23", "kuning": "#efc531", "hijau": "#2e7d4f", "biru": "#2d5bb9",
  "ungu": "#6e4a9e", "merah muda": "#e99ab4", "coklat": "#7a4e2d",
};

// Keadaan MICA dan teks yang ditampilkan di pojok kanan atas.
const STATUS_TEXT = {
  idle: "Menunggu pengunjung",
  ready: "Menunggu pertanyaan",
  thinking: "Mencari jawaban",
  speaking: "Sedang berbicara",
  listening: "Mendengarkan",
  transcribing: "Mengenali ucapan",
};

let greetingsSeen = 0;     // berapa sapaan yang sudah ditampilkan
let activeId = null;       // track_id pengunjung yang sedang dilayani (= ID sesi chat)
let idleTimer = null;      // pengatur waktu untuk kembali ke tampilan awal
let audio = null;          // suara yang sedang diputar
let speechCount = 0;       // bertambah setiap ada kalimat baru untuk diucapkan
let microphone = null;     // aliran suara dari mikrofon, diminta sekali lalu dipakai ulang
let recorder = null;       // MediaRecorder yang sedang merekam
let recordingTimer = null; // pengatur waktu untuk menghentikan rekaman otomatis

const el = (id) => document.getElementById(id);

// ---------- Sapaan dari kamera ----------

async function fetchGreetings() {
  try {
    const response = await fetch(`/greetings?since=${greetingsSeen}`);
    const greetings = await response.json();
    el("disconnected").hidden = true;
    for (const greeting of greetings) {
      greetingsSeen += 1;
      startSession(greeting);
    }
  } catch (error) {
    el("disconnected").hidden = false; // server mati atau sedang dimulai ulang
  }
}

function startSession(greeting) {
  // Pengunjung baru = sesi chat baru: percakapan sebelumnya dibersihkan.
  activeId = greeting.track_id;
  el("conversation").replaceChildren();
  const hex = SWATCH_COLORS[greeting.color] || "#8e918f";
  const message = addMessage("mica", greeting.text, "greeting");
  message.style.setProperty("--shirt-color", hex);

  // Kartu target diisi warna baju, dengan animasi "dituang".
  const card = el("target");
  card.style.setProperty("--shirt-color", hex);
  card.classList.remove("empty", "fresh");
  void card.offsetWidth; // memaksa browser mengulang animasi
  card.classList.add("fresh");
  el("target-name").textContent = greeting.color;
  el("target-note").textContent =
    `Pengunjung nomor ${greeting.track_id}, terbaca di ${greeting.votes.replace("/", " dari ")} frame`;

  setStatus("ready");
  resetIdleTimer();
  speak(greeting.text);
}

function goIdle() {
  activeId = null;
  clearTimeout(idleTimer);
  stopSpeaking();
  showIntro();
  const card = el("target");
  card.classList.remove("fresh");
  card.classList.add("empty");
  el("target-name").textContent = "belum ada";
  el("target-note").textContent = "Berdiri di depan kamera supaya MICA menyapamu.";
  setStatus("idle");
}

function showIntro() {
  const title = document.createElement("p");
  title.className = "intro";
  title.textContent = "Halo, aku MICA.";
  const note = document.createElement("p");
  note.className = "intro-note";
  note.textContent = "Aku menjawab pertanyaan seputar kuliah di Mikroskil. "
    + "Berdiri di depan kamera supaya aku sapa, atau langsung pilih topik di bawah.";
  el("conversation").replaceChildren(title, note);
}

// ---------- Bertanya ----------

async function ask(text) {
  if (el("conversation").querySelector(".intro")) el("conversation").replaceChildren(); // hapus perkenalan
  stopSpeaking(); // pengunjung bertanya lagi: MICA berhenti bicara
  addMessage("visitor", text);
  const pending = addMessage("mica", "Sebentar, MICA mencari jawabannya…", "pending");
  el("send-button").disabled = true;
  setStatus("thinking");

  try {
    const response = await postJson("/ask", { track_id: activeId, text });
    const result = await response.json();
    pending.remove();
    addMessage("mica", result.answer || result.error || "Jawaban tidak terbaca. Coba kirim lagi.");
    if (result.answer) speak(result.answer);
  } catch (error) {
    pending.remove();
    addMessage("mica", "Pertanyaan belum terkirim karena MICA terputus dari server. Coba kirim lagi.");
  } finally {
    el("send-button").disabled = false;
    returnToCalm();
    resetIdleTimer();
  }
}

el("ask-form").addEventListener("submit", (e) => {
  e.preventDefault(); // jangan muat ulang halaman
  const input = el("ask-input");
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  ask(text);
  input.focus();
});

// Tombol topik: yang dikirim adalah pertanyaan lengkap di atribut data-question.
for (const button of document.querySelectorAll(".topics button")) {
  button.addEventListener("click", () => ask(button.dataset.question));
}

// ---------- Berbicara (TTS) ----------

async function speak(text) {
  // Minta MP3 dari server, lalu putar. Kalimat baru selalu menggantikan kalimat yang sedang diucapkan.
  const number = ++speechCount;
  stopSpeaking();
  try {
    const response = await postJson("/speak", { text });
    if (!response.ok) return; // misalnya internet putus: MICA tetap jalan, hanya tanpa suara
    const mp3 = await response.blob();
    if (number !== speechCount) return; // sementara menunggu, sudah ada kalimat yang lebih baru
    audio = new Audio(URL.createObjectURL(mp3));
    audio.addEventListener("ended", stopSpeaking);
    setStatus("speaking");
    await audio.play();
  } catch (error) {
    stopSpeaking(); // browser menolak memutar, atau server tidak terjangkau
  }
}

function stopSpeaking() {
  if (audio) {
    audio.pause();
    URL.revokeObjectURL(audio.src); // lepaskan memori MP3
    audio = null;
  }
  if (el("status").dataset.status === "speaking") returnToCalm();
}

// ---------- Mendengar (tombol bicara, STT) ----------

el("talk-button").addEventListener("click", () => {
  if (recorder && recorder.state === "recording") recorder.stop(); // tekan kedua: selesai bicara
  else startRecording();                                           // tekan pertama: mulai bicara
});

async function startRecording() {
  stopSpeaking(); // MICA diam dulu supaya suaranya sendiri tidak ikut terekam
  try {
    // Browser meminta izin mikrofon saat pertama kali. Pilih "Izinkan".
    if (!microphone) microphone = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (error) {
    addMessage("mica", "Mikrofon belum diizinkan. Klik ikon kunci di samping alamat halaman, izinkan mikrofon, lalu coba lagi.");
    return;
  }
  const chunks = [];
  recorder = new MediaRecorder(microphone);
  recorder.addEventListener("dataavailable", (e) => chunks.push(e.data));
  recorder.addEventListener("stop", () => sendRecording(new Blob(chunks, { type: recorder.mimeType })));
  recorder.start();

  el("talk-button").classList.add("recording");
  el("talk-button-text").textContent = "Selesai bicara";
  setStatus("listening");
  recordingTimer = setTimeout(() => recorder.stop(), MAX_RECORDING_MS);
  resetIdleTimer();
}

async function sendRecording(recording) {
  clearTimeout(recordingTimer);
  el("talk-button").classList.remove("recording");
  el("talk-button-text").textContent = "Tekan untuk bicara";
  el("talk-button").disabled = true;
  setStatus("transcribing");

  let text = "";
  try {
    const response = await fetch("/transcribe", { method: "POST", body: recording });
    text = (await response.json()).text || "";
  } catch (error) {
    el("disconnected").hidden = false;
  }
  el("talk-button").disabled = false;
  returnToCalm();

  if (text) ask(text); // ucapan yang dikenali dikirim seperti pertanyaan yang diketik
  else addMessage("mica", "Maaf, MICA tidak menangkap suaramu. Tekan tombol bicara dan coba lagi.");
}

// Browser hanya mengizinkan suara setelah halaman disentuh atau diklik sekali.
// Jadi saat kios dinyalakan, petugas menekan tombol "Mulai" ini satu kali.
el("start-button").addEventListener("click", () => {
  el("start-screen").hidden = true;
});

// ---------- Bantuan ----------

// role: "mica" atau "visitor". extraClass: misalnya "greeting" atau "pending".
function addMessage(role, text, extraClass = "") {
  const p = document.createElement("p");
  p.className = `message from-${role} ${extraClass}`.trim();
  p.textContent = text;
  el("conversation").append(p);
  el("conversation").scrollTop = el("conversation").scrollHeight; // gulir ke pesan terbaru
  return p;
}

function postJson(url, body) {
  return fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

function setStatus(name) {
  el("status").dataset.status = name;
  el("status-text").textContent = STATUS_TEXT[name];
}

// Selesai berbicara, mendengar, atau menjawab: kembali ke keadaan tenang yang sesuai.
function returnToCalm() {
  setStatus(activeId ? "ready" : "idle");
}

function resetIdleTimer() {
  clearTimeout(idleTimer);
  if (activeId) idleTimer = setTimeout(goIdle, IDLE_TIMEOUT_MS);
}

// Jika aliran video belum siap, tampilkan pesan dan coba lagi tiap 2 detik.
el("video").addEventListener("error", () => {
  el("camera-empty").hidden = false;
  setTimeout(() => {
    el("camera-empty").hidden = true;
    el("video").src = `/video?t=${Date.now()}`;
  }, 2000);
});

showIntro();
setInterval(fetchGreetings, 500);
