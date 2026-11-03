"""PROD-5: python -m mica.eval stt-sweep (E-05, docs/AMANDEMEN-2026-11-03.md bagian A).

Rekaman sintetis: nada (pengganti ucapan), derau Gauss, dan diam. VAD dan STT palsu: prob dari
RMS potongan, STT memberi teks dan no_speech_prob menurut RMS. Angka di sini data uji, bukan ambang.
"""

import csv
import json
import wave
from pathlib import Path

import numpy as np
import pytest

import mica.eval.__main__ as cli
from mica.audio.stt import SegmentStats, Transcript
from mica.eval import stt_sweep as sw
from mica.eval.stt import SpeechItem

ROOT = Path(__file__).resolve().parents[2]
DEV_YAML = ROOT / "config" / "dev.yaml"
PROD_YAML = ROOT / "config" / "prod.yaml"
RATE = 16000


def _tone(seconds, amp=12000):
    t = np.arange(int(seconds * RATE)) / RATE
    return (amp * np.sin(2 * np.pi * 440 * t)).astype(np.int16)


def _noise(seconds, sd=3200, seed=20261103):
    rng = np.random.default_rng(seed)
    return np.clip(rng.normal(0, sd, int(seconds * RATE)), -32768, 32767).astype(np.int16)


def _silence(seconds):
    return np.zeros(int(seconds * RATE), dtype=np.int16)


def _rms(pcm):
    return float(np.sqrt(np.mean(np.asarray(pcm, dtype=np.float64) ** 2))) if len(pcm) else 0.0


def rms_prob():
    """prob ucapan palsu: nada 1,0; derau sekitar 0,4; diam 0."""
    return lambda chunk: min(1.0, _rms(chunk) / 8000)


class ToneStt:
    """STT palsu tanpa penyaring: nada -> pertanyaan (no_speech 0,1), derau -> halusinasi
    (no_speech 0,5), selain itu kosong (no_speech 0,9)."""

    def __init__(self, question="biaya kuliah berapa", noise_text="terima kasih"):
        self.question, self.noise_text = question, noise_text
        self.calls = 0
        self.last_segments = []

    def transcribe(self, pcm16k):
        self.calls += 1
        rms = _rms(pcm16k)
        text, p = ((self.question, 0.1) if rms > 6000 else
                   (self.noise_text, 0.5) if rms > 1000 else ("", 0.9))  # fmt: skip
        self.last_segments = [SegmentStats(p, -0.3)]
        return Transcript(text, bool(text), 0.05, len(pcm16k) / RATE)


def _items():
    return [
        SpeechItem("q1", None, "pertanyaan", "biaya kuliah berapa", None, "P01"),
        SpeechItem("q2", None, "pertanyaan", "biaya kuliah berapa", None, "P01"),  # pendek
        SpeechItem("q3", None, "pertanyaan", "biaya kuliah berapa", None, "P02"),  # 16 s
        SpeechItem("d1", None, "diam", None, None, "P01"),
        SpeechItem("b1", None, "bising", None, None, "P02"),
    ]


def _audio():
    return {
        "q1": np.concatenate([_silence(0.3), _tone(2.0), _silence(0.3)]),
        "q2": np.concatenate([_silence(0.3), _tone(0.2), _silence(0.3)]),
        "q3": _tone(16.0),
        "d1": _silence(2.0),
        "b1": _noise(2.0),
    }


def _observe(stt=None):
    return sw.observe(_items(), _audio(), stt or ToneStt(), rms_prob(), progress=lambda s: None)


# --- observasi --------------------------------------------------------------------------


def test_stt_called_at_most_three_times_per_recording():
    stt = ToneStt()
    obs = _observe(stt)
    assert len(obs) == 3 * 5
    # derau hanya lolos VAD pada threshold 0,3; diam tidak pernah
    assert stt.calls == 4 + 3 + 3
    voice = {(o.id, o.threshold): o.voice for o in obs}
    assert voice[("b1", 0.3)] and not voice[("b1", 0.5)] and not voice[("b1", 0.7)]
    assert not any(voice[("d1", t)] for t in sw.THRESHOLDS)


def test_observation_text_is_scrubbed_and_normalized():
    obs = _observe(ToneStt(question="Hubungi 081234567890, ya!"))
    q1 = next(o for o in obs if o.id == "q1")
    assert q1.hypothesis_norm == "hubungi telepon ya" and "0812" not in json.dumps(
        [o.__dict__ for o in obs]
    )


def test_filter_order_matches_audio_worker():
    o = sw.Observation("x", "pertanyaan", 0.5, 1.0, True, True, 0.1, (0.9,), (-0.2,), "a", 0.1)
    assert sw.filter_reason(o, 250.0, 0.6) == "min_speech"  # sebelum STT
    assert sw.filter_reason(o, 0.0, 0.6) == "no_speech"
    assert sw.filter_reason(o, 0.0, 0.95) is None
    silent = sw.Observation("x", "diam", 0.5, 1.0, False, False, None, (), (), "", None)
    assert sw.filter_reason(silent, 0.0, 0.8) == "no_voice"


# --- A1 ---------------------------------------------------------------------------------


def _rows():
    refs = {i.id: i.reference for i in _items() if i.kind == "pertanyaan"}
    return sw.evaluate_grid(_observe(), refs)


def test_grid_has_27_combinations_with_expected_counts():
    rows = {r.combo: r for r in _rows()}
    assert len(rows) == 27
    # q2 (bicara 0,19 s) tersaring min_speech 250 dan 500
    assert rows[(0.5, 250.0, 0.6)].filtered == {"no_voice": 0, "min_speech": 1, "no_speech": 0}
    assert rows[(0.5, 0.0, 0.6)].questions_filtered == 0
    # derau pada threshold 0,3: transkripsi palsu, kecuali no_speech 0,4 menyaringnya
    assert rows[(0.3, 0.0, 0.6)].false_transcripts == 1
    assert rows[(0.3, 0.0, 0.4)].false_transcripts == 0
    assert rows[(0.7, 0.0, 0.8)].false_transcripts == 0
    assert rows[(0.5, 0.0, 0.6)].wer_total == 0.0
    # pertanyaan tersaring dihitung sebagai hipotesis kosong untuk WER (dilaporkan saja)
    assert rows[(0.5, 250.0, 0.6)].wer_total == pytest.approx(1 / 3)


def test_winner_lexicographic_then_closest_to_library_default():
    winner = sw.choose(_rows())
    # (0,5; 0; 0,6): 0 tersaring, 0 palsu, jarak 1. (0,3; 0; 0,4) jarak 3, (0,7; 0; *) >= 2
    assert winner.combo == (0.5, 0.0, 0.6)


def _row(combo, filtered=0, false=0):
    return sw.GridRow(*combo, 3, {"no_voice": filtered, "min_speech": 0, "no_speech": 0}, 2,
                      false, None, None)  # fmt: skip


def test_rule_filtered_questions_dominate_false_transcripts():
    a = _row((0.5, 250.0, 0.6), filtered=1, false=0)
    b = _row((0.7, 500.0, 0.8), filtered=0, false=2)
    assert sw.choose([a, b]) is b


def test_rule_false_transcripts_before_distance():
    a = _row((0.5, 250.0, 0.6), false=1)
    b = _row((0.7, 500.0, 0.8), false=0)
    assert sw.choose([a, b]) is b


def test_rule_distance_to_library_default():
    a = _row((0.7, 500.0, 0.8))
    b = _row((0.5, 250.0, 0.6))
    c = _row((0.3, 250.0, 0.6))
    assert sw.choose([a, c, b]) is b
    assert sw.grid_distance(a.combo) == 3 and sw.grid_distance(b.combo) == 0


@pytest.mark.parametrize(
    ("first", "second", "expected"),
    [
        ((0.7, 250.0, 0.6), (0.3, 250.0, 0.6), 1),  # threshold lebih kecil
        ((0.5, 500.0, 0.6), (0.5, 0.0, 0.6), 1),  # min_speech lebih kecil
        ((0.5, 250.0, 0.4), (0.5, 250.0, 0.8), 1),  # no_speech lebih besar
    ],
)
def test_rule_final_tiebreak_filters_less(first, second, expected):
    rows = [_row(first), _row(second)]
    assert sw.grid_distance(rows[0].combo) == sw.grid_distance(rows[1].combo)
    assert sw.choose(rows) is rows[expected]


# --- A2 ---------------------------------------------------------------------------------


def test_max_utterance_counts_cut_questions_and_prefers_15():
    kinds = {i.id: i.kind for i in _items()}
    rows = sw.evaluate_max_utterance({"q1": 2.6, "q2": 0.8, "q3": 16.0, "d1": 40.0,
                                      "b1": 2.0}, kinds)  # fmt: skip
    assert [r.cut for r in rows] == [1, 0, 0]  # diam 40 s tidak dihitung
    assert sw.choose_max(rows).max_utterance_s == 20.0
    short = sw.evaluate_max_utterance({"q1": 2.0, "q2": 1.0, "q3": 3.0, "d1": 1.0,
                                       "b1": 1.0}, kinds)  # fmt: skip
    assert sw.choose_max(short).max_utterance_s == 15.0


def test_max_utterance_none_pass_picks_fewest_cut():
    rows = [sw.MaxRow(15.0, 3, 3), sw.MaxRow(20.0, 3, 2), sw.MaxRow(30.0, 3, 1)]
    assert sw.choose_max(rows).max_utterance_s == 30.0


# --- run dan CLI ------------------------------------------------------------------------


def test_run_sweep_writes_outputs_and_reanalysis_matches(tmp_path):
    winner, max_winner = sw.run_sweep(_items(), _audio(), ToneStt(), rms_prob(),
                                      tmp_path / "r1", {"note": "sintetis"},
                                      progress=lambda s: None)  # fmt: skip
    assert winner.combo == (0.5, 0.0, 0.6) and max_winner.max_utterance_s == 20.0
    run = tmp_path / "r1"
    grid = list(csv.DictReader((run / "grid.csv").open(encoding="utf-8-sig")))
    assert len(grid) == 27 and sum(int(r["pemenang"]) for r in grid) == 1
    verdict = (run / "verdict.md").read_text(encoding="utf-8")
    assert "pertanyaan asli tersaring pada pemenang: 0 dari 3" in verdict
    assert "pertanyaan terpotong pada pemenang: 0 dari 3" in verdict
    info = json.loads((run / "run.json").read_text(encoding="utf-8"))
    assert info["winner"]["vad.min_speech_ms"] == 0.0 and info["note"] == "sintetis"
    (tmp_path / "r2").mkdir()
    again = sw.analyze(sw.read_observations(run / "observations.jsonl"), _items(),
                       tmp_path / "r2", {})  # fmt: skip
    assert again[0].combo == winner.combo
    assert (tmp_path / "r2" / "grid.csv").read_bytes() == (run / "grid.csv").read_bytes()


def test_analyze_rejects_unknown_ids(tmp_path):
    obs = [o for o in _observe() if o.id != "q1"]
    with pytest.raises(sw.SweepError, match="tidak ada di manifest"):
        sw.analyze(obs, _items()[1:3], tmp_path, {})


def _wav(path, pcm):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(np.asarray(pcm, dtype=np.int16).tobytes())


def _dataset(tmp_path):
    rows = []
    for item in _items():
        _wav(tmp_path / f"{item.id}.wav", _audio()[item.id])
        row = {"id": item.id, "file": f"{item.id}.wav", "jenis": item.kind,
               "penutur": item.speaker, "persetujuan": True}  # fmt: skip
        if item.reference:
            row["referensi"] = item.reference
        rows.append(row)
    path = tmp_path / "manifest.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


def test_cli_end_to_end_with_fakes_and_offline_rerun(tmp_path, capsys):
    from mica.eval.stt import SttCandidate

    manifest = _dataset(tmp_path)
    seen = []

    def candidates(args, settings, no_speech):
        seen.append(no_speech)
        return [SttCandidate("palsu", True, ToneStt(), {"backend": "palsu"})]

    out = tmp_path / "out"
    args = cli.build_parser().parse_args(["stt-sweep", "--config", str(DEV_YAML), "--dataset",
                                          str(manifest), "--out", str(out), "--run-name", "a",
                                          "--note", "sintetis"])  # fmt: skip
    assert cli.cmd_stt_sweep(args, candidates, prob_factory=rms_prob) == 0
    assert seen == [None]  # STT tanpa penyaring no_speech
    text = capsys.readouterr().out
    assert "audio.vad.threshold = 0.5" in text and "audio.max_utterance_s = 20" in text
    assert not list(out.rglob("*.wav"))
    rerun = cli.build_parser().parse_args(["stt-sweep", "--config", str(DEV_YAML), "--dataset",
                                           str(manifest), "--out", str(out), "--run-name", "b",
                                           "--observations",
                                           str(out / "a" / "observations.jsonl")])  # fmt: skip
    assert cli.cmd_stt_sweep(rerun, lambda *a: pytest.fail("STT tidak boleh dipanggil")) == 0
    assert (out / "b" / "grid.csv").read_bytes() == (out / "a" / "grid.csv").read_bytes()


def test_cli_rejected_in_prod(tmp_path, capsys):
    manifest = _dataset(tmp_path)
    code = cli.main(["stt-sweep", "--config", str(PROD_YAML), "--dataset", str(manifest)])
    assert code == 2 and "mode prod" in capsys.readouterr().err


def test_cli_refused_in_prod_even_when_complete(monkeypatch):
    from mica.config import load_settings

    settings = load_settings(DEV_YAML)
    prod = settings.model_copy(update={"app": settings.app.model_copy(update={"mode": "prod"})})
    monkeypatch.setattr(cli, "load_settings", lambda *a, **k: prod)
    args = cli.build_parser().parse_args(["stt-sweep", "--config", "x", "--dataset", "y"])
    with pytest.raises(cli.SttEvalError, match="app.mode: dev"):
        cli.cmd_stt_sweep(args)


def test_cli_rejects_multiple_threads(tmp_path, capsys):
    manifest = _dataset(tmp_path)
    code = cli.main(["stt-sweep", "--config", str(DEV_YAML), "--dataset", str(manifest),
                     "--threads", "2,4"])  # fmt: skip
    assert code == 2 and "satu nilai" in capsys.readouterr().err
