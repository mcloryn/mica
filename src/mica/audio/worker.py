"""M-08 audio worker: proses suara di proses anak bus M-13 (SDD 3.2, 3.3, 5.2; ADR-20).

run_audio_worker(cfg, inbox, outbox) berjalan di proses anak (multiprocessing spawn). Isinya:
- thread utama proses: membaca inbox (bus.to_audio): ListenControl, Speak, StopSpeaking, Shutdown;
- thread rekam: MicStream -> SpeechSegmenter, hanya saat mode auto/push_to_talk dan MICA tidak
  sedang bicara atau mentranskripsi; awal ucapan -> SpeechStarted;
- thread kerja: antrean tugas berurutan, STT lalu TTS (SDD 3.3).

Perilaku:
- Saat start: muat Whisper dan Piper, buka mikrofon dan speaker, lalu AudioStatus(ready=True).
  Tanpa mikrofon -> mic_ok=False (MIC_DOWN) dan Speak tetap dilayani; tanpa speaker ->
  speaker_ok=False dan Speak langsung dijawab SpeechDone(tts_first_audio_s=None).
- Mode awal off. push_to_talk menangkap tepat satu ucapan berikutnya, lalu mode menjadi off.
- Penyaring audio.vad.min_speech_ms (sebelum STT) dan audio.stt.no_speech_threshold (di
  FasterWhisperStt). Transcript tersaring tetap dikirim dengan ok=False, text="" dan filtered_by.
- Speak: mikrofon di-pause (K-6), sintesis per kalimat; kalimat berikutnya disintesis selama
  kalimat sebelumnya diputar. tts_first_audio_s = Speak diterima worker -> clip pertama mulai
  diputar. Selesai -> SpeechDone; mikrofon dibuka lagi hanya bila mode masih auto/push_to_talk.
- StopSpeaking: pemutaran dihentikan (sounddevice stop), kalimat sisa dan Speak yang masih antre
  dibuang, masing-masing dijawab SpeechDone(interrupted=True).
- session_id dari ListenControl/Speak terakhir ditempel ke SpeechStarted dan Transcript.
- Teks transkripsi tidak pernah di-log (N-09); audio hanya di memori (N-08). diagnose (dev saja)
  mencetak statistik VAD/Whisper ke konsol, tanpa teks.
- faster-whisper, piper, dan sounddevice hanya diimpor di proses ini.

AudioWorkerConfig dibuat di proses utama (from_settings) dan harus bisa di-pickle. Nilai VAD
TBD (null) tanpa nilai coba ditolak sebelum spawn. Factory palsu ("modul:fungsi") hanya untuk
dev dan tes.
"""

from __future__ import annotations

import importlib
import logging
import queue
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mica.audio.messages import (
    AudioStatus,
    ListenControl,
    ListenMode,
    ReleaseTalk,
    Speak,
    SpeechDone,
    SpeechStarted,
    StopSpeaking,
    Transcript,
)
from mica.audio.player import SpeakerUnavailable
from mica.audio.stt import DEFAULT_WHISPER_DIR, MODEL_FILES, SttModelMissing, whisper_dir
from mica.audio.stt import Transcript as SttTranscript
from mica.audio.tts import DEFAULT_VOICES_DIR, VoiceMissing, voice_path
from mica.audio.vad import (
    SAMPLE_RATE,
    SpeechSegmenter,
    Utterance,
    is_too_short,
    push_to_talk_utterance,
)
from mica.audio.vad import SpeechStarted as VadStarted
from mica.config import Settings
from mica.core.logsetup import configure_dev_logging

VAD_KEYS = ("vad.threshold", "vad.min_silence_ms", "max_utterance_s")
log = logging.getLogger(__name__)
FILTER_KEYS = ("vad.min_speech_ms", "stt.no_speech_threshold")
IDLE_WAIT_S = 0.05  # non-ADR: jeda cek ulang thread rekam saat tidak mendengarkan
READ_TIMEOUT_S = 0.1  # non-ADR: batas tunggu satu potongan mikrofon supaya perubahan mode cepat


class AudioWorkerConfigError(Exception):
    pass


def _config_value(settings: Settings, key: str) -> Any:
    node: Any = settings.audio
    for part in key.split("."):
        node = getattr(node, part)
    return node


@dataclass(frozen=True)
class AudioWorkerConfig:
    mode: str
    whisper_dir: str
    compute_type: str
    stt_threads: int | None
    voice_file: str
    length_scale: float | None
    values: dict[str, float]  # VAD_KEYS, wajib
    filters: dict[str, float | None]  # FILTER_KEYS, None = penyaring mati
    mic_device: int | None = None
    speaker_device: int | None = None
    diagnose: bool = False  # dev saja: statistik VAD/Whisper ke konsol
    # dev/tes saja: "modul:fungsi"; mic_factory(device, options), stt/tts/player_factory(cfg,
    # options), prob_factory(options)
    mic_factory: str | None = None
    stt_factory: str | None = None
    tts_factory: str | None = None
    player_factory: str | None = None
    prob_factory: str | None = None
    factory_options: dict[str, Any] = field(default_factory=dict)
    tts_threads: int | None = None  # audio.tts.threads; None = bawaan onnxruntime
    # dev saja (--measure-preview): selang sintesis/putar ke antrean pengukuran
    measure: bool = False

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        overrides: Mapping[str, float | None] | None = None,
        *,
        whisper_root: Path = DEFAULT_WHISPER_DIR,
        voices_dir: Path = DEFAULT_VOICES_DIR,
        mic_device: int | None = None,
        speaker_device: int | None = None,
        diagnose: bool = False,
        mic_factory: str | None = None,
        stt_factory: str | None = None,
        tts_factory: str | None = None,
        player_factory: str | None = None,
        prob_factory: str | None = None,
        factory_options: Mapping[str, Any] | None = None,
    ) -> AudioWorkerConfig:
        """overrides: nilai coba untuk VAD_KEYS dan FILTER_KEYS (kunci tanpa awalan audio.)."""
        overrides = dict(overrides or {})
        stt = settings.audio.stt
        if stt.backend != "faster_whisper":
            raise AudioWorkerConfigError(f"audio.stt.backend {stt.backend} belum dibuat (E-05)")
        values: dict[str, float] = {}
        missing = []
        for key in VAD_KEYS:
            value = overrides.get(key)
            value = _config_value(settings, key) if value is None else value
            if value is None:
                missing.append(f"audio.{key}")
            else:
                values[key] = float(value)
        if missing:
            raise AudioWorkerConfigError(
                "nilai TBD (null) di config, worker tidak dimulai: " + ", ".join(missing)
            )
        filters: dict[str, float | None] = {}
        for key in FILTER_KEYS:
            value = overrides.get(key)
            value = _config_value(settings, key) if value is None else value
            filters[key] = None if value is None else float(value)
        cfg = cls(
            mode=settings.app.mode,
            whisper_dir=whisper_dir(stt.model, whisper_root).as_posix(),
            compute_type=stt.compute_type,
            stt_threads=stt.threads,
            voice_file=voice_path(settings.audio.tts.voice, voices_dir).as_posix(),
            length_scale=settings.audio.tts.length_scale,
            tts_threads=settings.audio.tts.threads,
            values=values,
            filters=filters,
            mic_device=mic_device,
            speaker_device=speaker_device,
            diagnose=diagnose,
            mic_factory=mic_factory,
            stt_factory=stt_factory,
            tts_factory=tts_factory,
            player_factory=player_factory,
            prob_factory=prob_factory,
            factory_options=dict(factory_options or {}),
        )
        cfg.validate()
        return cfg

    def _factories(self) -> list[str | None]:
        return [self.mic_factory, self.stt_factory, self.tts_factory, self.player_factory,
                self.prob_factory]  # fmt: skip

    def validate(self) -> None:
        if self.mode == "dev":
            return
        if any(self._factories()):
            raise AudioWorkerConfigError(
                "factory audio palsu hanya boleh saat app.mode: dev (ditolak di kiosk)"
            )
        if self.diagnose:
            raise AudioWorkerConfigError("diagnosis konsol hanya boleh saat app.mode: dev")
        if self.measure:
            raise AudioWorkerConfigError("pengukuran pratinjau hanya boleh saat app.mode: dev")

    def check_files(self) -> None:
        """Model Whisper dan suara Piper harus ada sebelum proses anak dimulai."""
        if self.stt_factory is None:
            root = Path(self.whisper_dir)
            if not all((root / name).is_file() for name in MODEL_FILES):
                raise SttModelMissing(root)
        if self.tts_factory is None:
            for path in (Path(self.voice_file), Path(f"{self.voice_file}.json")):
                if not path.is_file():
                    raise VoiceMissing(path)


def load_factory(path: str) -> Callable[..., Any]:
    module, sep, name = path.partition(":")
    if not sep or not module or not name:
        raise AudioWorkerConfigError(f"factory harus berformat modul:fungsi, didapat {path!r}")
    return getattr(importlib.import_module(module), name)


def _make_stt(cfg: AudioWorkerConfig) -> Any:
    if cfg.stt_factory is not None:
        return load_factory(cfg.stt_factory)(cfg, cfg.factory_options)
    from mica.audio.stt import FasterWhisperStt

    return FasterWhisperStt(Path(cfg.whisper_dir), cfg.compute_type, cfg.stt_threads,
                            cfg.filters["stt.no_speech_threshold"])  # fmt: skip


def _make_tts(cfg: AudioWorkerConfig) -> Any:
    if cfg.tts_factory is not None:
        return load_factory(cfg.tts_factory)(cfg, cfg.factory_options)
    from mica.audio.tts import PiperTts

    return PiperTts(Path(cfg.voice_file), cfg.length_scale, threads=cfg.tts_threads)


def _make_mic(cfg: AudioWorkerConfig) -> Any:
    if cfg.mic_factory is not None:
        return load_factory(cfg.mic_factory)(cfg.mic_device, cfg.factory_options)
    from mica.audio.mic import MicStream

    return MicStream(cfg.mic_device)


def _make_player(cfg: AudioWorkerConfig) -> Any:
    if cfg.player_factory is not None:
        return load_factory(cfg.player_factory)(cfg, cfg.factory_options)
    from mica.audio.player import SounddevicePlayer

    return SounddevicePlayer(cfg.speaker_device)


def _make_prob(cfg: AudioWorkerConfig) -> Callable[[Any], float]:
    if cfg.prob_factory is not None:
        return load_factory(cfg.prob_factory)(cfg.factory_options)
    from mica.audio.vad import silero_prob

    return silero_prob()


class AudioLoop:
    """Isi proses suara; dipisah dari run_audio_worker supaya bisa diuji di satu proses.
    mic None = tidak ada mikrofon; player None = tidak ada speaker."""

    def __init__(
        self,
        cfg: AudioWorkerConfig,
        inbox: Any,
        outbox: Any,
        stt: Any,
        tts: Any,
        mic: Any | None,
        player: Any | None,
        prob: Callable[[Any], float],
        mic_message: str = "",
        speaker_message: str = "",
        clock: Callable[[], float] = time.monotonic,
        out: Callable[[str], None] = print,
        measure_out: Any = None,
    ) -> None:
        self.cfg = cfg
        self.inbox = inbox
        self.outbox = outbox
        self.stt = stt
        self.tts = tts
        self.mic = mic
        self.player = player
        self.mic_message = mic_message
        self.speaker_message = speaker_message
        self.clock = clock
        self.out = out
        self.prob = prob
        # push-to-talk (Langkah 42): potongan selama mode hold; dikirim saat ReleaseTalk atau
        # saat audio.max_utterance_s tercapai, dibuang bila mode berubah (dibatalkan)
        self.hold_chunks: list[Any] = []
        self.hold_samples = 0
        self.max_hold = int(cfg.values["max_utterance_s"] * SAMPLE_RATE)
        self.release_at: float | None = None
        self.segmenter = SpeechSegmenter(
            threshold=cfg.values["vad.threshold"],
            min_silence_ms=cfg.values["vad.min_silence_ms"],
            max_utterance_s=cfg.values["max_utterance_s"],
            prob=prob,
        )
        self.lock = threading.Lock()
        self.wake = threading.Event()
        self.tasks: queue.Queue[tuple[Any, ...] | None] = queue.Queue()
        self.mode: ListenMode = "off"
        self.session_id: str | None = None
        self.speaking = False
        self.transcribing = False
        self.mic_open = False  # mikrofon sedang di-resume; diubah hanya dengan self.lock
        self.epoch = 0  # naik pada setiap StopSpeaking; Speak dari epoch lama dibuang
        self.running = True
        self.error: BaseException | None = None
        self.meter: Any = None
        if measure_out is not None and cfg.measure:
            from mica.eval.preview_meter import AudioMeter

            self.meter = AudioMeter(measure_out, clock)
            self.meter.info(tts)

    # --- status -----------------------------------------------------------------------

    def _send(self, msg: Any) -> None:
        self.outbox.put(msg)

    def _status(self) -> None:
        parts = [self.mic_message or "mikrofon siap", self.speaker_message or "speaker siap"]
        self._send(AudioStatus(mic_ok=self.mic is not None, speaker_ok=self.player is not None,
                               ready=True, message="; ".join(parts)))  # fmt: skip

    def _listen_allowed(self) -> bool:
        """Dipanggil dengan self.lock dipegang."""
        return (
            self.running
            and self.mic is not None
            and self.mode != "off"
            and not self.speaking
            and not self.transcribing
        )

    def _should_listen(self) -> bool:
        with self.lock:
            return self._listen_allowed()

    # --- thread rekam -------------------------------------------------------------------

    def _record(self) -> None:
        assert self.mic is not None
        while self.running:
            # buka/tutup mikrofon di bawah lock yang sama dengan _speak, supaya mikrofon tidak
            # pernah dibuka lagi setelah _speak menutupnya (K-6)
            with self.lock:
                want = self._listen_allowed()
                if want and not self.mic_open:
                    self.segmenter.reset()  # start_s ucapan = waktu sejak mic resume
                    self.mic.resume()
                    self.mic_open = True
                    log.info("mikrofon direkam (mode %s)", self.mode)
                elif not want and self.mic_open:
                    self.mic.pause()
                    self.mic_open = False
                    log.info("mikrofon dijeda (mode %s)", self.mode)
            if not want:
                self.wake.wait(IDLE_WAIT_S)
                self.wake.clear()
                continue
            chunk = self.mic.read_chunk(timeout_s=READ_TIMEOUT_S)
            if chunk is None:
                self.wake.wait(0.01)
                continue
            if not self._should_listen():
                continue  # mode/bicara berubah saat membaca: potongan dibuang
            if self._hold_chunk(chunk):
                continue
            for event in self.segmenter.feed(chunk):
                if isinstance(event, VadStarted):
                    log.info("VAD: awal ucapan")
                    self._send(SpeechStarted(self.session_id, self.clock()))
                elif isinstance(event, Utterance):
                    log.info("VAD: ucapan selesai (%.2f s, terpotong batas=%s)", event.audio_s,
                             event.cut_by_max)  # fmt: skip
                    with self.lock:
                        session = self.session_id
                        self.transcribing = True
                        if self.mode == "push_to_talk":
                            self.mode = "off"  # tepat satu ucapan
                        self.mic.pause()
                        self.mic_open = False
                    self.tasks.put(("stt", event, session, self.clock()))
                    break

    def _hold_chunk(self, chunk: Any) -> bool:
        """Mode hold: simpan potongan (di memori saja); kirim pada potongan pertama setelah
        tombol dilepas atau saat batas max_utterance_s tercapai."""
        with self.lock:
            if self.mode != "hold":
                return False
            self.hold_chunks.append(chunk)
            self.hold_samples += len(chunk)
            if self.release_at is not None:  # potongan ini = audio sampai tombol dilepas
                task = self._take_hold(cut_by_max=False, released=self.release_at)
            elif self.hold_samples >= self.max_hold:
                task = self._take_hold(cut_by_max=True, released=self.clock())
                log.info("push-to-talk: batas %.0f s tercapai, rekaman dikirim otomatis",
                         self.max_hold / SAMPLE_RATE)  # fmt: skip
            else:
                return True
        self.tasks.put(task)
        return True

    def _take_hold(self, cut_by_max: bool, released: float) -> tuple[Any, ...]:
        """Dipanggil dengan self.lock dipegang: tutup rekaman hold menjadi tugas STT."""
        import numpy as np

        pcm = (np.concatenate(self.hold_chunks) if self.hold_chunks
               else np.zeros(0, dtype=np.int16))  # fmt: skip
        self.hold_chunks, self.hold_samples, self.release_at = [], 0, None
        self.mode = "off"
        self.transcribing = True
        if self.mic is not None and self.mic_open:
            self.mic.pause()
            self.mic_open = False
        log.info("push-to-talk: rekaman %.2f s dikirim ke cek VAD", len(pcm) / SAMPLE_RATE)
        return ("ptt", pcm, self.session_id, released, cut_by_max)

    def _drop_hold(self, reason: str) -> None:
        """Dipanggil dengan self.lock dipegang: rekaman hold dibuang (dibatalkan)."""
        if self.mode == "hold":
            log.info("push-to-talk: rekaman dibatalkan (%s), %.2f s dibuang", reason,
                     self.hold_samples / SAMPLE_RATE)  # fmt: skip
        self.hold_chunks, self.hold_samples, self.release_at = [], 0, None

    # --- thread kerja -------------------------------------------------------------------

    def _work(self) -> None:
        while True:
            task = self.tasks.get()
            if task is None:
                return
            if task[0] == "stt":
                self._transcribe(task[1], task[2], task[3])
            elif task[0] == "ptt":
                self._transcribe_hold(*task[1:])
            else:
                self._speak(task[1], task[2], task[3])

    def _transcribe(self, utt: Utterance, session: str | None, ended: float | None = None) -> None:
        try:
            if is_too_short(utt, self.cfg.filters["vad.min_speech_ms"]):
                t = SttTranscript("", False, 0.0, utt.audio_s, filtered_by="min_speech")
            else:
                t = self.stt.transcribe(utt.pcm16k)
            # tanpa teks transkripsi (N-09)
            log.info("STT: ok=%s, %d karakter, %.2f s, tersaring=%s", t.ok, len(t.text or ""),
                     t.stt_s or 0.0, t.filtered_by)  # fmt: skip
            self._send(Transcript(session, t.text if t.ok else "", t.ok, t.stt_s, t.audio_s,
                                  utt.cut_by_max, t.filtered_by, utt.trailing_silence_s,
                                  ended))  # fmt: skip
            if self.cfg.diagnose:
                from mica.audio.listen import diagnose_lines

                segments = getattr(self.stt, "last_segments", None)
                for line in diagnose_lines(t, utt, segments):
                    self.out(f"[audio]{line}")
        finally:
            with self.lock:
                self.transcribing = False
            self.wake.set()

    def _transcribe_hold(self, pcm: Any, session: str | None, released: float,
                         cut_by_max: bool) -> None:  # fmt: skip
        """Push-to-talk: cek VAD (ada ucapan? pangkas hening) lalu STT; tanpa ucapan STT tidak
        dipanggil. vad_s = tombol dilepas sampai cek VAD selesai (amandemen 2 E-09)."""
        try:
            audio_s = len(pcm) / SAMPLE_RATE
            utt = push_to_talk_utterance(pcm, self.prob, self.cfg.values["vad.threshold"],
                                         cut_by_max)  # fmt: skip
            checked = self.clock()
            if utt is None:
                t = SttTranscript("", False, 0.0, audio_s, filtered_by="no_voice")
            elif is_too_short(utt, self.cfg.filters["vad.min_speech_ms"]):
                t = SttTranscript("", False, 0.0, utt.audio_s, filtered_by="min_speech")
            else:
                t = self.stt.transcribe(utt.pcm16k)
            log.info("push-to-talk: cek VAD %.3f s, ucapan=%s; STT ok=%s, %d karakter, %.2f s, "
                     "tersaring=%s", checked - released, utt is not None, t.ok,
                     len(t.text or ""), t.stt_s or 0.0, t.filtered_by)  # fmt: skip
            self._send(Transcript(session, t.text if t.ok else "", t.ok, t.stt_s, t.audio_s,
                                  cut_by_max, t.filtered_by, checked - released,
                                  checked))  # fmt: skip
        finally:
            with self.lock:
                self.transcribing = False
            self.wake.set()

    def _speak(self, msg: Speak, epoch: int, received: float) -> None:
        def done(first: float | None, interrupted: bool) -> None:
            first_t = None if first is None else received + first
            self._send(SpeechDone(msg.session_id, msg.utterance_id, first, interrupted, first_t))

        if epoch != self.epoch:
            done(None, True)  # StopSpeaking datang sebelum Speak ini mulai
            return
        if self.player is None:
            done(None, False)
            return
        with self.lock:
            self.speaking = True
            if self.mic is not None and self.mic_open:
                self.mic.pause()  # K-6: sebelum suara pertama keluar
                self.mic_open = False
        first: float | None = None
        interrupted = False
        synth_s: list[float] = []  # pengukuran (dev): waktu sintesis per clip
        audio_s = 0.0
        try:
            synth_start = self.clock()
            for clip in self.tts.stream(msg.text):
                if self.meter is not None:
                    synth_end = self.clock()
                    self.meter.synth(synth_start, synth_end)
                    synth_s.append(synth_end - synth_start)
                self.player.wait()  # clip sebelumnya
                if epoch != self.epoch:
                    interrupted = True
                    break
                self.player.start(clip)
                if self.meter is not None:
                    self.meter.play(self.clock(), clip.duration_s)
                    audio_s += clip.duration_s
                if first is None:
                    first = self.clock() - received
                synth_start = self.clock()
            self.player.wait()
            interrupted = interrupted or epoch != self.epoch
        except SpeakerUnavailable as exc:
            # perangkat keluaran hilang saat runtime; error sintesis tetap mematikan worker
            self.player = None
            self.speaker_message = str(exc)
            self._status()
        finally:
            with self.lock:
                self.speaking = False
            self.wake.set()
        if self.meter is not None:
            self.meter.speak(received, first, synth_s, audio_s, len(msg.text), interrupted)
        done(first, interrupted)

    # --- inbox --------------------------------------------------------------------------

    def handle(self, msg: Any) -> None:
        from mica.core.bus import Shutdown

        if isinstance(msg, Shutdown):
            self.running = False
        elif isinstance(msg, ListenControl):
            with self.lock:
                if self.mode == "hold" or msg.mode == "hold":
                    self._drop_hold(f"ListenControl({msg.mode})")
                self.mode = msg.mode
                self.session_id = msg.session_id
            log.info("ListenControl(%s) diterima proses suara", msg.mode)
        elif isinstance(msg, ReleaseTalk):
            with self.lock:
                if self.mode == "hold" and self.mic is not None and self.mic_open:
                    self.release_at = self.clock()  # thread rekam menutup rekaman
                elif self.mode == "hold":  # mikrofon belum sempat dibuka: rekaman kosong
                    self.tasks.put(self._take_hold(cut_by_max=False, released=self.clock()))
            log.info("ReleaseTalk diterima proses suara")
        elif isinstance(msg, Speak):
            with self.lock:
                self.session_id = msg.session_id
                epoch = self.epoch
            self.tasks.put(("speak", msg, epoch, self.clock()))
        elif isinstance(msg, StopSpeaking):
            with self.lock:
                self.epoch += 1
            if self.player is not None:
                self.player.stop()
        self.wake.set()

    def _guard(self, target: Callable[[], None]) -> Callable[[], None]:
        def run() -> None:
            try:
                target()
            except BaseException as exc:  # noqa: BLE001 - dilempar ulang di thread utama proses
                self.error = exc
                self.running = False

        return run

    def run(self) -> None:
        threads = [threading.Thread(target=self._guard(self._work), name="audio-kerja",
                                    daemon=True)]  # fmt: skip
        if self.mic is not None:
            threads.append(threading.Thread(target=self._guard(self._record),
                                            name="audio-rekam", daemon=True))  # fmt: skip
        for t in threads:
            t.start()
        self._status()
        try:
            while self.running:
                try:
                    msg = self.inbox.get(timeout=READ_TIMEOUT_S)
                except queue.Empty:
                    continue
                self.handle(msg)
        finally:
            self.running = False
            with self.lock:
                self.epoch += 1
            if self.player is not None:
                self.player.stop()
            self.tasks.put(None)
            self.wake.set()
            for t in threads:
                t.join(5.0)
            if self.mic is not None:
                self.mic.close()
        if self.error is not None:
            raise self.error


def run_audio_worker(
    cfg: AudioWorkerConfig, inbox: Any, outbox: Any, measure_out: Any = None
) -> None:
    """Entry proses anak. Error tak terduga dilaporkan sebagai AudioStatus(ready=False), lalu
    proses keluar dengan error supaya bus memulai ulang (SDD 8.1)."""
    from mica.audio.mic import MicUnavailable
    from mica.core import startup

    if cfg.mode == "dev":  # Langkah 42: log diagnosis proses anak terlihat di konsol dev
        configure_dev_logging()
    startup.set_process("audio")
    startup.mark("proc_start")
    try:
        cfg.validate()
        cfg.check_files()
        # Langkah 40: modul yang memang dimuat pabrik asli di bawah, dicatat waktunya
        for module, factory in (("faster_whisper", cfg.stt_factory), ("piper", cfg.tts_factory),
                                ("pysilero_vad", cfg.prob_factory),
                                ("sounddevice", cfg.mic_factory)):  # fmt: skip
            if factory is None:
                startup.timed_import(module)
        startup.mark("stt_load_start")
        stt = _make_stt(cfg)
        startup.mark("stt_load_done")
        tts = _make_tts(cfg)
        startup.mark("tts_load_done")
        prob = _make_prob(cfg)
        startup.mark("vad_load_done")
        mic, mic_message = None, ""
        try:
            mic = _make_mic(cfg)
            mic.pause()  # mode awal off
            log.info("mikrofon terbuka: perangkat %s, %s Hz%s", cfg.mic_device or "bawaan",
                     getattr(mic, "input_rate", "?"),
                     " (resample ke 16 kHz)" if getattr(mic, "resampled", False) else "")  # fmt: skip
        except MicUnavailable as exc:
            mic_message = str(exc)  # sudah diawali MIC_DOWN
            log.warning("mikrofon tidak tersedia: %s", exc)
        startup.mark("mic_open_done")
        player, speaker_message = None, ""
        try:
            player = _make_player(cfg)
        except SpeakerUnavailable as exc:
            speaker_message = f"speaker tidak tersedia: {exc}"
        startup.mark("player_open_done")
        AudioLoop(cfg, inbox, outbox, stt, tts, mic, player, prob, mic_message,
                  speaker_message, measure_out=measure_out).run()  # fmt: skip
    except Exception as exc:
        outbox.put(AudioStatus(mic_ok=False, speaker_ok=False, ready=False,
                               message=f"audio worker error: {exc}"))  # fmt: skip
        raise
