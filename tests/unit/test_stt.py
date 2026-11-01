"""M-08 STT: SpeechSegmenter, MicStream, FasterWhisperStt (palsu), WER, CLI listen."""

import csv
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from tests.fakes import FakeMic, FakeStt, FakeTts, fake_prob

import mica.audio.__main__ as cli
from mica.audio.listen import WER_FIELDS, Listener
from mica.audio.mic import MicStream, MicUnavailable, resample_int16
from mica.audio.stt import (
    MODEL_FILES,
    FasterWhisperStt,
    SegmentStats,
    SttModelMissing,
    effective_threads,
    is_no_speech,
    whisper_dir,
)
from mica.audio.vad import (
    CHUNK_SAMPLES,
    PAD_MS,
    SpeechSegmenter,
    SpeechStarted,
    Utterance,
    is_too_short,
)
from mica.config import load_settings
from mica.core.types import ErrorCode
from mica.eval.wer import corpus_wer, normalize_for_wer, wer

ROOT = Path(__file__).resolve().parents[2]
DEV_YAML = ROOT / "config" / "dev.yaml"
CHUNK_MS = CHUNK_SAMPLES / 16  # 32 ms
VAD = ["--vad-threshold", "0.5", "--min-silence-ms", "160", "--max-utterance-s", "1"]  # data uji


def _chunks(*segments):
    out = []
    for kind, n in segments:
        out += [np.full(CHUNK_SAMPLES, 1000 if kind == "bicara" else 0, dtype=np.int16)] * n
    return out


def _segmenter(min_silence_ms=160, max_utterance_s=10.0):
    # data uji, bukan ambang: 160 ms = 5 potongan
    return SpeechSegmenter(0.5, min_silence_ms, max_utterance_s, prob=fake_prob())


def _feed(seg, chunks):
    events = []
    for c in chunks:
        events += seg.feed(c)
    return events


# --- SpeechSegmenter ------------------------------------------------------------------


def test_speech_start_event():
    events = _feed(_segmenter(), _chunks(("diam", 3), ("bicara", 1)))
    assert events == [SpeechStarted(3 * CHUNK_SAMPLES / 16000)]


def test_short_pause_does_not_split():
    events = _feed(_segmenter(), _chunks(("bicara", 5), ("diam", 3), ("bicara", 5), ("diam", 5)))
    utterances = [e for e in events if isinstance(e, Utterance)]
    assert len(utterances) == 1 and not utterances[0].cut_by_max


def test_long_silence_ends_utterance_with_padding():
    seg = _segmenter()
    events = _feed(seg, _chunks(("diam", 4), ("bicara", 10), ("diam", 5)))
    (utt,) = [e for e in events if isinstance(e, Utterance)]
    pad = int(PAD_MS * 16)  # 480 sampel
    assert len(utt.pcm16k) == pad + 10 * CHUNK_SAMPLES + pad
    assert not utt.pcm16k[:pad].any() and not utt.pcm16k[-pad:].any()
    assert utt.pcm16k[pad : pad + 10 * CHUNK_SAMPLES].all()
    assert utt.audio_s == pytest.approx(len(utt.pcm16k) / 16000)


def test_cut_at_max_utterance():
    seg = _segmenter(max_utterance_s=0.32)  # 5120 sampel
    events = _feed(seg, _chunks(("bicara", 25)))
    utterances = [e for e in events if isinstance(e, Utterance)]
    assert utterances and all(u.cut_by_max for u in utterances)
    assert all(len(u.pcm16k) <= 0.32 * 16000 + CHUNK_SAMPLES for u in utterances)


def test_reset_discards_partial_speech():
    seg = _segmenter()
    _feed(seg, _chunks(("bicara", 5)))
    seg.reset()
    assert _feed(seg, _chunks(("diam", 10))) == []


def test_utterance_diagnostics():
    events = _feed(_segmenter(), _chunks(("diam", 4), ("bicara", 3), ("diam", 2), ("bicara", 2),
                                         ("diam", 5)))  # fmt: skip
    (utt,) = [e for e in events if isinstance(e, Utterance)]
    assert utt.speech_s == pytest.approx(7 * CHUNK_SAMPLES / 16000)  # tanpa padding dan ekor diam
    assert utt.start_s == pytest.approx(4 * CHUNK_SAMPLES / 16000)
    assert utt.n_above == 5 and utt.prob_max == 1.0
    assert utt.prob_mean == pytest.approx(5 / 12)


# --- penyaring min_speech / no_speech (nilai di bawah adalah data uji, bukan ambang) ----------


def test_min_speech_filter():
    short = _feed(_segmenter(), _chunks(("bicara", 3), ("diam", 5)))[-1]  # 96 ms
    assert is_too_short(short, 100) and not is_too_short(short, 90)
    assert not is_too_short(short, None)  # null = mati


def test_listener_min_speech_skips_stt():
    stt = FakeStt(["terima kasih"])
    utt = _feed(_segmenter(), _chunks(("bicara", 3), ("diam", 5)))[-1]
    t = Listener(FakeMic([]), _segmenter(), stt, min_speech_ms=100).transcribe(utt)
    assert (t.ok, t.text, t.filtered_by, stt.calls) == (False, "", "min_speech", 0)
    t = Listener(FakeMic([]), _segmenter(), stt, min_speech_ms=None).transcribe(utt)
    assert t.ok and t.filtered_by is None and stt.calls == 1


def test_is_no_speech():
    seg = [SegmentStats(0.7, -0.3), SegmentStats(0.5, -0.2)]
    assert not is_no_speech(seg, 0.6)  # satu segmen di bawah ambang
    assert is_no_speech(seg, 0.5)  # >= ambang
    assert not is_no_speech(seg, None) and not is_no_speech([], 0.1)


def test_whisper_no_speech_filter(tmp_path):
    segs = [FakeSegment(" Terima kasih.", no_speech_prob=0.8, avg_logprob=-0.4)]
    stt = FasterWhisperStt(_model_dir(tmp_path), no_speech_threshold=0.7,
                           loader=lambda *a: FakeWhisper(segs))  # fmt: skip
    t = stt.transcribe(np.zeros(16000, dtype=np.int16))
    assert (t.ok, t.text, t.filtered_by) == (False, "", "no_speech")
    assert stt.last_segments == [SegmentStats(0.8, -0.4)]
    stt.no_speech_threshold = None
    t = stt.transcribe(np.zeros(16000, dtype=np.int16))
    assert t.ok and t.text == "Terima kasih." and t.filtered_by is None


# --- MicStream -------------------------------------------------------------------------


class FakeInputStream:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.callback = kwargs["callback"]
        self.started = self.closed = False

    def start(self):
        self.started = True

    def stop(self):
        pass

    def close(self):
        self.closed = True

    def push(self, samples):
        self.callback(np.asarray(samples, dtype=np.int16).reshape(-1, 1), len(samples), None, None)


def _mic(rate=16000, supports=True):
    streams = []

    def factory(**kwargs):
        streams.append(FakeInputStream(**kwargs))
        return streams[-1]

    mic = MicStream(None, factory, supports_16k=lambda d: supports, device_rate=lambda d: rate)
    return mic, streams[0]


def test_mic_returns_fixed_chunks():
    mic, stream = _mic()
    assert stream.kwargs["samplerate"] == 16000 and stream.kwargs["dtype"] == "int16"
    stream.push(np.arange(700))
    stream.push(np.arange(400))
    first = mic.read_chunk(0.01)
    assert len(first) == CHUNK_SAMPLES and first[0] == 0
    assert len(mic.read_chunk(0.01)) == CHUNK_SAMPLES
    assert mic.read_chunk(0.01) is None  # sisa 76 sampel belum cukup


def test_mic_pause_drops_audio_and_buffer():
    mic, stream = _mic()
    stream.push(np.full(300, 5))  # di buffer sebelum pause
    mic.pause()
    stream.push(np.full(2000, 7))  # masuk saat pause: dibuang
    mic.resume()
    assert mic.read_chunk(0.01) is None
    stream.push(np.full(CHUNK_SAMPLES, 9))
    assert set(mic.read_chunk(0.01).tolist()) == {9}


def test_mic_resamples_when_16k_unsupported():
    mic, stream = _mic(rate=48000, supports=False)
    assert mic.resampled and stream.kwargs["samplerate"] == 48000
    stream.push(np.full(48000 // 10, 100))
    assert len(mic.read_chunk(0.01)) == CHUNK_SAMPLES


def test_mic_unavailable_code():
    def no_device(device):
        raise MicUnavailable("tidak ada mikrofon")

    with pytest.raises(MicUnavailable) as err:
        MicStream(None, FakeInputStream, device_rate=no_device)
    assert err.value.code == ErrorCode.MIC_DOWN


def test_resample_length():
    x = np.zeros(22050, dtype=np.int16)
    assert len(resample_int16(x, 22050, 16000)) == 16000


# --- FasterWhisperStt -------------------------------------------------------------------


class FakeSegment:
    def __init__(self, text, no_speech_prob=0.0, avg_logprob=0.0):
        self.text = text
        self.no_speech_prob = no_speech_prob
        self.avg_logprob = avg_logprob


class FakeWhisper:
    def __init__(self, texts):
        self.texts = texts  # str atau FakeSegment
        self.kwargs = None

    def transcribe(self, audio, **kwargs):
        self.kwargs = kwargs
        self.audio = audio
        segs = [t if isinstance(t, FakeSegment) else FakeSegment(t) for t in self.texts]
        return iter(segs), None


def _model_dir(tmp_path):
    d = tmp_path / "faster-whisper-small"
    d.mkdir()
    for name in MODEL_FILES:
        (d / name).write_bytes(b"x")
    return d


def test_whisper_parameters_and_text(tmp_path):
    fake = FakeWhisper([" Biaya kuliah", " berapa? "])
    loaded = []
    stt = FasterWhisperStt(
        _model_dir(tmp_path), "int8", None, loader=lambda *a: loaded.append(a) or fake
    )
    t = stt.transcribe(np.zeros(16000, dtype=np.int16))
    assert t.text == "Biaya kuliah berapa?" and t.ok and t.audio_s == 1.0
    assert fake.kwargs == {
        "language": "id",
        "condition_on_previous_text": False,
        "vad_filter": False,
    }
    assert fake.audio.dtype == np.float32
    assert loaded[0][1:] == ("int8", 0)  # threads null -> 0 (bawaan library)


def test_whisper_empty_text_not_ok(tmp_path):
    stt = FasterWhisperStt(_model_dir(tmp_path), loader=lambda *a: FakeWhisper(["  "]))
    assert not stt.transcribe(np.zeros(1600, dtype=np.int16)).ok


def test_stt_model_missing(tmp_path):
    with pytest.raises(SttModelMissing) as err:
        FasterWhisperStt(tmp_path / "tidak-ada", loader=lambda *a: None)
    assert err.value.code == ErrorCode.STT_MODEL_MISSING


def test_effective_threads(monkeypatch):
    monkeypatch.delenv("OMP_NUM_THREADS", raising=False)
    assert effective_threads(None) == 4 and effective_threads(6) == 6
    monkeypatch.setenv("OMP_NUM_THREADS", "2")
    assert effective_threads(None) == 2


def test_fetch_stt_model_verifies_sha256(tmp_path, monkeypatch):
    payload = {name: name.encode() for name in cli.WHISPER_SHA256}
    monkeypatch.setattr(
        cli, "WHISPER_SHA256", {n: hashlib.sha256(b).hexdigest() for n, b in payload.items()}
    )
    urls = []

    def download(url, dest):
        urls.append(url)
        dest.write_bytes(payload[url.rsplit("/", 1)[1]])

    assert cli.cmd_fetch_stt_model(load_settings(DEV_YAML), tmp_path, download) == 0
    assert all(f"/resolve/{cli.WHISPER_REVISION}/" in u for u in urls)
    assert sorted(p.name for p in whisper_dir("small", tmp_path).iterdir()) == sorted(payload)


# --- WER ------------------------------------------------------------------------------


def test_wer_normalization():
    assert normalize_for_wer("Biaya S1, Rp14.000.000?") == "biaya es satu empat belas juta rupiah"
    assert normalize_for_wer("Nomor WA-nya  berapa ya?!") == "nomor wa nya berapa ya"
    assert wer("Admisi buka 09.00 WIB.", "admisi buka pukul sembilan waktu indonesia barat") == 0
    assert wer("satu dua tiga", "") == 1.0
    assert corpus_wer(["a b c d", "e f"], ["a b c d", "e"]) == pytest.approx(1 / 6)


# --- listen ---------------------------------------------------------------------------


def _listen(argv, mic, stt, answers=(), tts=None, played=None):
    answers = list(answers)
    played = played if played is not None else []
    args = cli.build_parser().parse_args(["listen", *VAD, *argv])
    return cli.cmd_listen(
        args,
        load_settings(DEV_YAML),
        mic_factory=lambda device: mic,
        stt_factory=lambda settings, root, no_speech: stt,
        prob_factory=fake_prob,
        tts_factory=lambda path, scale: tts or FakeTts(),
        play=lambda clip, device: played.append(clip.duration_s),
        ask=lambda prompt: answers.pop(0),
    )


def test_listen_requires_vad_values(capsys):
    assert cli.main(["listen", "--config", str(DEV_YAML)]) == 2
    err = capsys.readouterr().err
    assert "--vad-threshold" in err and "--min-silence-ms" in err and "--max-utterance-s" in err


def test_listen_prints_text_and_echo_pauses_mic(capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    mic = FakeMic([("diam", 3), ("bicara", 8), ("diam", 6)] * 2)
    stt = FakeStt(["biaya kuliah berapa", "admisi buka kapan"])
    played = []
    assert _listen(["--echo", "--count", "2"], mic, stt, played=played) == 0
    out = capsys.readouterr().out
    assert "nilai coba" in out and out.count("mendengarkan") == 2
    assert "teks: biaya kuliah berapa" in out and "RTF" in out
    assert out.count("[mic pause]") == 2 and out.count("[mic resume]") == 2
    assert mic.events == ["resume", "pause", "resume", "pause", "resume"] and len(played) == 2
    assert mic.closed and list(tmp_path.iterdir()) == []  # tidak ada file


def test_listen_script_writes_wer_csv_and_run_json(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    mic = FakeMic([("diam", 2), ("bicara", 6), ("diam", 6)] * 3)
    questions = tmp_path / "q.jsonl"
    rows = [
        {"qid": "d003", "question": "Pendaftaran S1 gelombang satu sampai kapan?", "type": "answerable"},
        {"qid": "d001", "question": "Biaya kuliah Sistem Informasi berapa?", "type": "answerable"},
        {"qid": "d002", "question": "Cuaca hari ini?", "type": "out_of_kb"},
    ]  # fmt: skip
    questions.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    stt = FakeStt(["biaya kuliah sistem informasi", "biaya kuliah sistem informasi berapa", "pendaftaran es satu gelombang satu sampai kapan"])  # fmt: skip
    out = tmp_path / "results" / "pilot"
    argv = ["--script", "--n", "2", "--dataset", str(questions), "--out", str(out)]
    assert _listen(argv, mic, stt, answers=["r", "", ""]) == 0
    files = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file())
    assert files == ["q.jsonl", "results/pilot/run.json", "results/pilot/wer.csv"]
    with (out / "wer.csv").open(encoding="utf-8-sig") as f:
        got = list(csv.DictReader(f))
    assert list(got[0]) == list(WER_FIELDS)
    assert [r["qid"] for r in got] == ["d001", "d003"]
    assert got[0]["ulang"] == "1" and float(got[0]["wer"]) == 0.0
    assert got[1]["referensi_norm"] == "pendaftaran es satu gelombang satu sampai kapan"
    info = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert info["wer_total"] == 0.0 and info["wer_normalization"].startswith("normalize_for_speech")
    assert info["vad"]["sources"]["vad.threshold"] == "nilai coba"
    assert (out / "wer.csv").read_bytes().startswith(b"\xef\xbb\xbf")


def test_listen_filtered_utterance_not_echoed(capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # ucapan 1 pendek (3 potongan = 96 ms) tersaring; ucapan 2 lolos dan diucapkan ulang
    mic = FakeMic([("diam", 3), ("bicara", 3), ("diam", 6), ("bicara", 8), ("diam", 6)])
    stt = FakeStt(["biaya kuliah berapa"])
    played = []
    argv = ["--echo", "--count", "2", "--min-speech-ms", "100", "--no-speech-threshold", "0.6"]
    assert _listen(argv, mic, stt, played=played) == 0
    out = capsys.readouterr().out
    assert "audio.vad.min_speech_ms = 100.0 (nilai coba)" in out
    assert "audio.stt.no_speech_threshold = 0.6 (nilai coba)" in out
    assert out.count("[tersaring: min_speech]") == 1 and "whisper: dilewati" in out
    assert "sejak mic resume" in out and "potongan >= ambang" in out
    assert stt.calls == 1 and len(played) == 1 and out.count("[mic pause]") == 1
    assert list(tmp_path.iterdir()) == []


def test_listen_filters_off_when_null(capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    mic = FakeMic([("diam", 3), ("bicara", 3), ("diam", 6)])
    assert _listen(["--count", "1"], mic, FakeStt(["terima kasih"])) == 0
    out = capsys.readouterr().out
    assert "audio.vad.min_speech_ms = None (mati, null TBD E-05)" in out
    assert "tersaring" not in out


def test_listen_script_needs_out():
    with pytest.raises(cli.AudioCliError, match="--out"):
        _listen(["--script"], FakeMic([]), FakeStt())


def test_listen_refused_in_prod():
    s = load_settings(DEV_YAML)
    prod = s.model_copy(update={"app": s.app.model_copy(update={"mode": "prod"})})
    args = cli.build_parser().parse_args(["listen", *VAD])
    with pytest.raises(cli.AudioCliError, match="app.mode: dev"):
        cli.cmd_listen(args, prod, mic_factory=lambda d: FakeMic([]))


def test_audio_modules_do_not_import_torch():
    code = (
        "import sys\n"
        "import mica.audio.normalize, mica.audio.tts, mica.audio.vad, mica.audio.mic\n"
        "import mica.audio.stt, mica.audio.listen, mica.audio.__main__, mica.eval.wer\n"
        "print('torch' in sys.modules)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True, cwd=ROOT
    )
    assert result.stdout.strip() == "False"


def test_utterance_trailing_silence_is_vad_delay():
    events = _feed(_segmenter(), _chunks(("diam", 2), ("bicara", 6), ("diam", 5)))
    (utt,) = [e for e in events if isinstance(e, Utterance)]
    assert utt.trailing_silence_s == pytest.approx(5 * CHUNK_SAMPLES / 16000)  # timings.vad
    cut = _feed(_segmenter(max_utterance_s=0.32), _chunks(("bicara", 12)))
    assert next(e.trailing_silence_s for e in cut if isinstance(e, Utterance)) == 0.0
