"""python -m mica setup / check / entry point, tanpa jaringan, perangkat, jendela, atau Groq.

File model dibuat palsu di tmp_path dan sha256 terkunci dipalsukan lewat monkeypatch.
"""

import hashlib
import json
from pathlib import Path

import pytest
import yaml

import mica.__main__ as entry
import mica.audio.__main__ as audio_cli
from mica import check, setup
from mica.audio import stt
from mica.config import load_settings
from mica.setup import Downloaders
from mica.vision import color, detector

ROOT = Path(__file__).resolve().parents[2]
DEV_YAML = ROOT / "config" / "dev.yaml"
PROD_YAML = ROOT / "config" / "prod.yaml"
FAKE_KEY = "gsk_rahasia_palsu_123456"  # kunci palsu, tidak pernah boleh tercetak
DEVICES = [{"name": "Mic", "max_input_channels": 1, "max_output_channels": 0},
           {"name": "Speaker", "max_input_channels": 0, "max_output_channels": 2}]  # fmt: skip


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def locked(monkeypatch):
    """Isi palsu per file; sha256 terkunci diganti sha isi palsu itu."""
    content = {
        "yolo26n.pt": b"yolo", "yolo26n-pose.pt": b"pose", "color_names_w2c.npy": b"warna",
        **{n: n.encode() for n in stt.WHISPER_SHA256},
        **{n: n.encode() for n in audio_cli.VOICE_SHA256},
    }  # fmt: skip
    monkeypatch.setattr(detector, "MODEL_SHA256", {"yolo26n": _sha(b"yolo"),
                                                   "yolo26n-pose": _sha(b"pose")})  # fmt: skip
    import mica.vision.__main__ as vision_cli

    monkeypatch.setattr(vision_cli, "MODEL_SHA256", detector.MODEL_SHA256)
    monkeypatch.setattr(color, "COLORS_NPY_SHA256", _sha(b"warna"))
    monkeypatch.setattr(stt, "WHISPER_SHA256", {n: _sha(n.encode()) for n in stt.WHISPER_SHA256})
    monkeypatch.setattr(audio_cli, "WHISPER_SHA256", stt.WHISPER_SHA256)
    monkeypatch.setattr(audio_cli, "VOICE_SHA256",
                        {n: _sha(n.encode()) for n in audio_cli.VOICE_SHA256})  # fmt: skip
    return content


def _fake_downloaders(content, calls):
    def yolo(path):
        calls.append(path.name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content[path.name])
        return path

    def embedder(model, revision, cache_dir):
        calls.append("bge")
        snap = Path(cache_dir) / f"models--{model.replace('/', '--')}" / "snapshots" / revision
        for f in setup.EMBEDDER_FILES:
            (snap / f).parent.mkdir(parents=True, exist_ok=True)
            (snap / f).write_bytes(b"x")

    def url_file(url, dest):
        calls.append(url.rsplit("/", 1)[1])
        dest.write_bytes(content[url.rsplit("/", 1)[1]])

    def colors(models_dir, download):
        calls.append("colors")
        path = Path(models_dir) / "color_names_w2c.npy"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content["color_names_w2c.npy"])
        return path

    return Downloaders(yolo=yolo, url_bytes=lambda url: b"", url_file=url_file,
                       embedder=embedder), colors  # fmt: skip


# --- setup ----------------------------------------------------------------------------------


def test_setup_downloads_all_then_skips(tmp_path, locked, monkeypatch):
    calls: list = []
    dl, colors = _fake_downloaders(locked, calls)
    import mica.vision.__main__ as vision_cli

    monkeypatch.setattr(vision_cli, "fetch_colors", colors)
    out: list[str] = []
    settings = load_settings(DEV_YAML)
    assert setup.run_setup(settings, models_dir=tmp_path, dl=dl, out=out.append) == 0
    table = "\n".join(out)
    assert table.count("diunduh") == 6 and "gagal" not in table
    assert calls[:3] == ["yolo26n-pose.pt", "yolo26n.pt", "colors"] and "bge" in calls
    calls.clear()
    out.clear()
    assert setup.run_setup(settings, models_dir=tmp_path, dl=dl, out=out.append) == 0
    assert "\n".join(out).count("sudah ada") == 6 and calls == []


def test_setup_only_one_component(tmp_path, locked):
    calls: list = []
    dl, _colors = _fake_downloaders(locked, calls)
    out: list[str] = []
    settings = load_settings(DEV_YAML)
    assert setup.run_setup(settings, "yolo26n", tmp_path, dl, out.append) == 0
    assert calls == ["yolo26n.pt"]
    assert setup.run_setup(settings, "tidak-ada", tmp_path, dl, out.append) == 2


def test_setup_reports_wrong_sha_without_overwriting(tmp_path, locked):
    (tmp_path / "yolo26n.pt").write_bytes(b"rusak")
    out: list[str] = []
    dl, _ = _fake_downloaders(locked, [])
    assert setup.run_setup(load_settings(DEV_YAML), "yolo26n", tmp_path, dl, out.append) == 1
    assert "sha256 tidak cocok" in "\n".join(out)
    assert (tmp_path / "yolo26n.pt").read_bytes() == b"rusak"


def test_setup_bge_blocked_when_revision_null(tmp_path, locked):
    settings = load_settings(PROD_YAML, require_complete=False)
    out: list[str] = []
    dl, _ = _fake_downloaders(locked, [])
    assert setup.run_setup(settings, "BGE-M3", tmp_path, dl, out.append) == 1
    assert "kb.embedder.revision null" in "\n".join(out)


# --- check ----------------------------------------------------------------------------------


def _models(tmp_path, content, settings):
    dl, colors = _fake_downloaders(content, [])
    for c in setup.components(settings, tmp_path, dl):
        if c.name == "tabel warna":
            colors(tmp_path, None)
        elif c.fetch is not None and c.used:
            c.fetch()


def _dev_config(tmp_path, backend=None):
    raw = yaml.safe_load(DEV_YAML.read_text(encoding="utf-8"))
    raw["logging"]["dir"] = str(tmp_path / "logs")
    if backend is not None:
        raw["ui"]["backend"] = backend
    path = tmp_path / "dev.yaml"
    path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    return path


def _run(tmp_path, config, monkeypatch, key=FAKE_KEY, devices=DEVICES):
    if key:
        monkeypatch.setenv("GROQ_API_KEY", key)
    else:
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
    return check.run_check(config, None, tmp_path, ROOT / "data" / "kb", lambda: devices)


def _web_config(tmp_path):
    return _dev_config(tmp_path, backend="web")


def test_check_all_ok_in_dev(tmp_path, locked, monkeypatch):
    config = _dev_config(tmp_path)
    _models(tmp_path, locked, load_settings(config))
    rows, _settings = _run(tmp_path, config, monkeypatch)
    assert not check.failed(rows), check.format_table(rows)
    table = check.format_table(rows)
    assert FAKE_KEY not in table and "ada (nilai tidak ditampilkan)" in table
    assert "diperiksa saat start" in table and "SEMUA OK" in table


def test_check_prod_nulls_listed_by_key(tmp_path, locked, monkeypatch):
    rows, settings = _run(tmp_path, PROD_YAML, monkeypatch)
    config_row = rows[0]
    assert config_row.status == "GAGAL"
    for key in ("kb.embedder.revision", "audio.vad.threshold", "session.idle_reset_s",
                "llm.chain[0]"):  # fmt: skip
        assert key in config_row.message
    assert settings is not None and check.failed(rows)


def test_check_missing_and_wrong_model(tmp_path, locked, monkeypatch):
    config = _dev_config(tmp_path)
    _models(tmp_path, locked, load_settings(config))
    (tmp_path / "piper" / "id_ID-news_tts-medium.onnx").unlink()
    (tmp_path / "yolo26n-pose.pt").write_bytes(b"salah")
    rows, _ = _run(tmp_path, config, monkeypatch)
    by_item = {r.item: r for r in rows}
    assert by_item["model yolo26n-pose"].status == "GAGAL"
    assert "sha256 tidak cocok" in by_item["model yolo26n-pose"].message
    voice = by_item["model suara id_ID-news_tts-medium"]
    assert voice.status == "GAGAL" and "file hilang" in voice.message
    assert "python -m mica setup" in voice.message


def test_check_missing_key_and_devices(tmp_path, locked, monkeypatch):
    config = _dev_config(tmp_path)
    _models(tmp_path, locked, load_settings(config))
    rows, _ = _run(tmp_path, config, monkeypatch, key=None, devices=DEVICES[1:])
    by_item = {r.item: r for r in rows}
    assert by_item["GROQ_API_KEY"].status == "GAGAL"
    assert "GROQ_API_KEY di file .env" in by_item["GROQ_API_KEY"].message
    assert by_item["perangkat audio"].status == "PERINGATAN"
    assert "mikrofon tidak ditemukan" in by_item["perangkat audio"].message
    assert "aplikasi tetap bisa dipakai lewat teks" in by_item["perangkat audio"].message


def test_check_device_warning_only_exits_zero(tmp_path, locked, monkeypatch):
    config = _dev_config(tmp_path)
    _models(tmp_path, locked, load_settings(config))
    rows, _ = _run(tmp_path, config, monkeypatch, devices=[])
    assert not check.failed(rows)
    assert {r.item: r for r in rows}["perangkat audio"].status == "PERINGATAN"
    assert "SIAP DENGAN PERINGATAN" in check.format_table(rows)
    monkeypatch.setattr(check, "run_check", lambda c, e: (rows, None))
    assert check.main([]) == 0  # hanya PERINGATAN: kode keluar 0


def test_check_key_value_never_printed(tmp_path, locked, monkeypatch, capsys):
    config = _dev_config(tmp_path)
    monkeypatch.setenv("GROQ_API_KEY", FAKE_KEY)
    monkeypatch.setattr(check, "_query_devices", lambda: DEVICES)
    code = check.main(["--config", str(config), "--env-file", str(tmp_path / "tidak-ada.env")])
    out = capsys.readouterr()
    assert code == 1  # model palsu tidak ada di folder models/ tmp: tetap tidak bocor
    assert FAKE_KEY not in out.out + out.err


def test_check_has_no_edge_row(tmp_path, locked, monkeypatch):
    # RF-2: UI dibuka di browser default; check tidak lagi mencari msedge.exe
    config = _web_config(tmp_path)
    _models(tmp_path, locked, load_settings(config))
    rows, _ = _run(tmp_path, config, monkeypatch)
    assert "Microsoft Edge" not in {r.item for r in rows}
    assert not check.failed(rows), check.format_table(rows)


def test_check_logs_not_writable(tmp_path, locked, monkeypatch):
    blocker = tmp_path / "bukan-folder"
    blocker.write_text("x", encoding="utf-8")
    raw = yaml.safe_load(DEV_YAML.read_text(encoding="utf-8"))
    raw["logging"]["dir"] = str(blocker / "logs")
    config = tmp_path / "dev.yaml"
    config.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    rows, _ = _run(tmp_path, config, monkeypatch)
    assert {r.item: r for r in rows}["folder log"].status == "GAGAL"


# --- entry point --------------------------------------------------------------------------


def test_main_check_failed_does_not_launch(capsys):
    launched = []
    rows = [check.CheckRow("config", "GAGAL", "mode prod: 1 kunci belum diisi: x")]
    code = entry.main([], check=lambda c, e: (rows, None),
                      launch=lambda s, a: launched.append(s) or 0)  # fmt: skip
    assert code == 1 and launched == []
    out = capsys.readouterr().out
    assert "GAGAL" in out and "MICA tidak dijalankan" in out


def test_main_check_ok_launches_with_default_prod_config():
    settings = load_settings(DEV_YAML)
    seen = {}

    def fake_check(config, env_file):
        seen["config"] = config
        return [check.CheckRow("config", "OK", "ok")], settings

    code = entry.main([], check=fake_check, launch=lambda s, a: seen.setdefault("s", s) and 0)
    assert code == 0 and seen["s"] is settings
    assert seen["config"] == Path("config/prod.yaml")


@pytest.mark.parametrize("backend", ["pyside6", "web"])
def test_main_launches_ui_by_backend(monkeypatch, backend):
    s = load_settings(DEV_YAML)
    settings = s.model_copy(update={"ui": s.ui.model_copy(update={"backend": backend})})
    calls = []
    for name in ("pyside6", "web"):
        monkeypatch.setitem(entry.LAUNCHERS, name,
                            lambda st, a, name=name: calls.append((name, a.fake_pipeline)) or 0)  # fmt: skip
    ok = [check.CheckRow("config", "OK", "ok")]
    assert entry.main(["--fake-pipeline"], check=lambda c, e: (ok, settings)) == 0
    assert calls == [(backend, True)]


def test_main_rejects_fake_flags_in_prod():
    settings = load_settings(DEV_YAML)
    prod = settings.model_copy(update={"app": settings.app.model_copy(update={"mode": "prod"})})
    ok = [check.CheckRow("config", "OK", "ok")]
    code = entry.main(["--fake-workers"], check=lambda c, e: (ok, prod),
                      launch=lambda s, a: 0)  # fmt: skip
    assert code == 2


def test_main_dispatches_subcommands(monkeypatch):
    import mica.check as check_mod
    import mica.setup as setup_mod

    monkeypatch.setattr(setup_mod, "main", lambda argv: 11)
    monkeypatch.setattr(check_mod, "main", lambda argv: 12)
    assert entry.main(["setup", "--only", "yolo26n"]) == 11
    assert entry.main(["check"]) == 12


def _test_set(path, questions):
    rows = [{"qid": f"o-test-{i:03d}", "question": q, "type": "answerable", "prev_qid": None,
             "gold_refs": [], "split": "test"} for i, q in enumerate(questions, 1)]  # fmt: skip
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


def _with_suggestions(tmp_path, suggestions):
    path = _dev_config(tmp_path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw["ui"]["suggestions"] = suggestions
    path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    return path


def test_check_catches_test_question_in_suggestions(tmp_path, locked, monkeypatch):
    config = _with_suggestions(tmp_path, {"Biaya": ["Biaya kuliah S1 berapa per tahun?"]})
    _models(tmp_path, locked, load_settings(config))
    test_set = _test_set(tmp_path / "test.jsonl", ["biaya KULIAH s1, berapa per tahun",
                                                   "Ada asrama?"])  # fmt: skip
    monkeypatch.setenv("GROQ_API_KEY", FAKE_KEY)
    rows, _ = check.run_check(config, None, tmp_path, ROOT / "data" / "kb", lambda: DEVICES,
                              test_set=test_set)  # fmt: skip
    leak = {r.item: r for r in rows}["kebocoran set uji"]
    assert leak.status == "GAGAL" and "o-test-001" in leak.message
    assert "o-test-002" not in leak.message and check.failed(rows)


def test_check_no_leak_ok_and_no_row_without_test_set(tmp_path, locked, monkeypatch):
    config = _with_suggestions(tmp_path, {"Biaya": ["Biaya kuliah S1 berapa per tahun?"]})
    _models(tmp_path, locked, load_settings(config))
    test_set = _test_set(tmp_path / "test.jsonl", ["Jalur beasiswa apa saja?"])
    monkeypatch.setenv("GROQ_API_KEY", FAKE_KEY)

    def run(path):
        return check.run_check(config, None, tmp_path, ROOT / "data" / "kb", lambda: DEVICES,
                               test_set=path)[0]  # fmt: skip

    leak = {r.item: r for r in run(test_set)}["kebocoran set uji"]
    assert leak.status == "OK" and "1 pertanyaan tidak identik/mirip" in leak.message
    assert "kebocoran set uji" not in {r.item for r in run(tmp_path / "tidak-ada.jsonl")}


def test_check_catches_test_question_in_topic_cards(tmp_path, locked, monkeypatch):
    # label kartu topik UI web ikut dicek
    config = _with_suggestions(tmp_path, {})
    _models(tmp_path, locked, load_settings(config))
    test_set = _test_set(tmp_path / "test.jsonl", ["Beasiswa?", "Ada asrama?"])
    monkeypatch.setenv("GROQ_API_KEY", FAKE_KEY)
    rows, _ = check.run_check(config, None, tmp_path, ROOT / "data" / "kb", lambda: DEVICES,
                              test_set=test_set)  # fmt: skip
    leak = {r.item: r for r in rows}["kebocoran set uji"]
    assert leak.status == "GAGAL" and "o-test-001" in leak.message and "ui.topics" in leak.message


def _with_topic_question(tmp_path, label, question):
    path = _dev_config(tmp_path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    for item in raw["ui"]["topics"]:
        if item["label"] == label:
            item["question"] = question
    path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    return path


def _run_leak(tmp_path, locked, monkeypatch, config, test_set, dev_sets):
    _models(tmp_path, locked, load_settings(config))
    monkeypatch.setenv("GROQ_API_KEY", FAKE_KEY)
    rows, _ = check.run_check(config, None, tmp_path, ROOT / "data" / "kb", lambda: DEVICES,
                              test_set=test_set,
                              dev_sets=dev_sets)  # fmt: skip
    return {r.item: r for r in rows}, rows


def test_check_catches_topic_question_identical_to_dev_and_test(tmp_path, locked, monkeypatch):
    # Langkah 53: question chip yang identik (setelah normalisasi) dengan set dev atau uji GAGAL
    config = _with_topic_question(tmp_path, "Beasiswa", "beasiswa APA aja yang ada di sini")
    dev_set = _test_set(tmp_path / "dev.jsonl", ["Beasiswa apa aja yang ada di sini?"])
    test_set = _test_set(tmp_path / "test.jsonl", ["Beasiswa apa aja yang ada di sini?"])
    by_item, rows = _run_leak(tmp_path, locked, monkeypatch, config, test_set, (dev_set,))
    for item in ("kebocoran set dev", "kebocoran set uji"):
        assert by_item[item].status == "GAGAL" and "o-test-001" in by_item[item].message
        assert "1.00" in by_item[item].message
    assert check.failed(rows)


def test_check_catches_similar_topic_question(tmp_path, locked, monkeypatch):
    # kemiripan token tinggi (bukan identik) juga GAGAL; kalimat lain tetap OK
    config = _with_topic_question(tmp_path, "Biaya", "Biaya kuliah S1 berapa per tahun ya?")
    dev_set = _test_set(tmp_path / "dev.jsonl", ["Biaya kuliah S1 berapa per tahun?",
                                                 "Cuaca di Medan hari ini gimana?"])  # fmt: skip
    by_item, _ = _run_leak(tmp_path, locked, monkeypatch, config, tmp_path / "x.jsonl", (dev_set,))
    leak = by_item["kebocoran set dev"]
    assert leak.status == "GAGAL" and "o-test-001" in leak.message
    assert "o-test-002" not in leak.message and "kebocoran set uji" not in by_item


def test_repo_topic_questions_pass_leak_check_against_data_eval():
    # pertanyaan chip di config/dev.yaml dan prod.yaml tidak identik/mirip data/eval
    from mica.eval.dataset import load_questions

    sets = [ROOT / "data/eval/questions.jsonl", ROOT / "data/eval/official/dev.jsonl",
            ROOT / "data/eval/official/test.jsonl"]  # fmt: skip
    questions = [q for p in sets if p.is_file() for q in load_questions(p)]
    assert questions
    for name in ("dev.yaml", "prod.yaml"):
        raw = yaml.safe_load((ROOT / "config" / name).read_text(encoding="utf-8"))
        hints = [t["question"] for t in raw["ui"]["topics"]] + [
            t["label"] for t in raw["ui"]["topics"]
        ]
        assert check.find_leaks(hints, questions) == [], name
