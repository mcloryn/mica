"""--trial-values (Langkah 41): nilai coba SDD bagian 12 hanya mengisi kunci null, di memori,
dev saja (kiosk ditolak), peringatan berisi kunci + nilai, label UI, pemilihan pekerja asli/palsu,
dan tanpa gambar/audio ke disk."""

import logging
import os
from pathlib import Path

import pytest
import yaml

from mica import trial
from mica.__main__ import main as mica_main
from mica.config import ConfigError, read_raw
from mica.ui.devfakes import FAKE_CAMERA_VALUES
from mica.webui import app as webui_app
from mica.webui import state
from mica.webui.server import STATIC_DIR, WebUi

ROOT = Path(__file__).resolve().parents[2]
DEV_YAML = ROOT / "config" / "dev.yaml"
KIOSK_YAML = ROOT / "config" / "kiosk.yaml"


def test_fill_nulls_only_fills_null_or_missing():
    raw = {"vision": {"dwell_s": 5.0, "leave_s": None, "color": {}}, "audio": {}}
    filled = trial.fill_nulls(raw)
    assert raw["vision"]["dwell_s"] == 5.0 and "vision.dwell_s" not in filled  # berisi: tetap
    assert raw["vision"]["leave_s"] == 3.0 and filled["vision.leave_s"] == 3.0
    assert raw["vision"]["color"]["min_majority"] == 0.6
    assert raw["audio"]["vad"]["threshold"] == 0.5
    assert set(filled) == set(trial.TRIAL_VALUES) - {"vision.dwell_s"}


def test_load_trial_settings_dev_in_memory_with_warning(caplog):
    before = DEV_YAML.read_bytes()
    caplog.set_level(logging.WARNING, logger="mica.trial")
    settings, filled = trial.load_trial_settings(DEV_YAML)
    assert DEV_YAML.read_bytes() == before  # config repo tidak berubah
    assert settings.vision.dwell_s == 2.0 and settings.audio.vad.threshold == 0.5
    assert settings.vision.conf == 0.1  # nilai dev yang sudah ada tidak diganti
    raw = read_raw(DEV_YAML)
    assert all(_get(raw, k) is None for k in filled)  # hanya kunci yang null di file
    (record,) = [r for r in caplog.records if r.name == "mica.trial"]
    assert record.levelno == logging.WARNING and "NILAI COBA" in record.getMessage()
    assert "vision.dwell_s=2.0" in record.getMessage()


def _get(raw, dotted):
    node = raw
    for key in dotted.split("."):
        node = (node or {}).get(key)
    return node


def test_trial_values_rejected_in_kiosk(capsys):
    with pytest.raises(ConfigError, match="hanya boleh saat app.mode: dev"):
        trial.load_trial_settings(KIOSK_YAML)
    assert webui_app.main(["--config", str(KIOSK_YAML), "--trial-values"]) == 2
    assert "hanya boleh saat app.mode: dev" in capsys.readouterr().err


def test_python_m_mica_trial_values(monkeypatch):
    launched = []

    def check(config, env):
        from mica.config import load_settings

        return [], load_settings(config, require_complete=False)

    def launch(settings, args):
        launched.append((settings, args))
        return 0

    assert mica_main(["--config", str(DEV_YAML), "--trial-values"], check, launch) == 0
    settings, args = launched[0]
    assert settings.vision.dwell_s == 2.0 and args.trial_values
    assert mica_main(["--config", str(KIOSK_YAML), "--trial-values"], check, launch) == 2
    assert len(launched) == 1  # kiosk tidak diluncurkan


def test_trial_badge_in_config_and_header():
    ui = trial.load_trial_settings(DEV_YAML)[0].ui
    c = state.config_json(ui, dev=True, trial=True)
    assert c["trial"] and c["texts"]["trial_badge"] == "NILAI COBA (dev)"
    assert not state.config_json(ui, dev=True)["trial"]
    assert not state.config_json(ui, dev=False, trial=True)["trial"]  # bukan dev: tidak ada
    assert WebUi(ui, dev=True, trial=True).trial
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert '<span id="trial_badge" class="trial-badge" hidden></span>' in html
    js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert '$("trial_badge").hidden = !c.trial' in js


def test_fake_camera_values_come_from_trial_values():
    assert FAKE_CAMERA_VALUES == {k.removeprefix("vision."): v
                                  for k, v in trial.TRIAL_VALUES.items() if k.startswith("vision.")}  # fmt: skip


def test_start_bus_combinations(monkeypatch):
    calls = []
    import mica.core.bus as bus_mod
    from mica.ui import devfakes

    monkeypatch.setattr(bus_mod, "start_workers",
                        lambda s, vision=None, workers=None: calls.append(("real", workers, vision))
                        or f"bus{workers}")  # fmt: skip
    monkeypatch.setattr(devfakes, "start_fake_camera", lambda s: calls.append(("fakecam",)) or "fc")
    monkeypatch.setattr(devfakes, "fake_camera_config", lambda s: "fake-cfg")
    s = trial.load_trial_settings(DEV_YAML)[0]
    # kamera asli + suara palsu
    bus = webui_app._start_bus(s, fake_workers=False, fake_camera=False, fake_voice=True)
    assert calls[-1] == ("real", ("vision",), None) and bus.vision == "bus('vision',)"
    # suara asli + sumber gambar palsu
    assert webui_app._start_bus(s, False, True, False) == "bus('vision', 'audio')"
    assert calls[-1] == ("real", ("vision", "audio"), "fake-cfg")
    # semua palsu (seperti sebelumnya)
    assert webui_app._start_bus(s, True, False, False).vision is None
    assert webui_app._start_bus(s, True, True, False).vision == "fc"
    # semua asli
    assert webui_app._start_bus(s, False, False, False) == "busNone"


def test_trial_values_write_nothing(tmp_path, monkeypatch):
    # tidak ada gambar/audio (atau file lain) yang ditulis saat memuat nilai coba (N-08)
    monkeypatch.chdir(tmp_path)
    trial.load_trial_settings(DEV_YAML)
    assert os.listdir(tmp_path) == []


def test_profile_script_uses_shared_trial_values(tmp_path):
    import importlib.util

    spec = importlib.util.spec_from_file_location("sp", ROOT / "scripts/startup_profile.py")
    sp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sp)
    assert sp.TRIAL_VALUES is trial.TRIAL_VALUES
    path, filled = sp.make_config(DEV_YAML, tmp_path)
    assert yaml.safe_load(path.read_text(encoding="utf-8"))["vision"]["dwell_s"] == 2.0
    assert filled == {k: v for k, v in trial.TRIAL_VALUES.items() if k in filled}
