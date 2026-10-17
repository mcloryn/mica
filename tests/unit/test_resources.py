"""Perekam sumber daya E-09 (mica.eval.resources): kelompok proses, CSV angka saja, izin mode."""

import csv
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

import mica.__main__ as entry
from mica import check
from mica.config import load_settings
from mica.eval import resources
from mica.eval.resources import (
    FIELDS,
    GROUPS,
    RecorderRefused,
    ResourceRecorder,
    bus_roots,
    check_allowed,
    make_recorder,
    pid_groups,
)

ROOT = Path(__file__).resolve().parents[2]
DEV_YAML = ROOT / "config" / "dev.yaml"


@pytest.fixture
def sleeper():
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    yield proc
    proc.kill()
    proc.wait()


def test_allowed_only_in_dev_or_with_e09():
    check_allowed("dev", False)
    check_allowed("dev", True)
    check_allowed("kiosk", True)
    with pytest.raises(RecorderRefused, match="--e09"):
        check_allowed("kiosk", False)
    with pytest.raises(RecorderRefused):
        make_recorder(Path("x"), "kiosk", False, dict)


def test_pid_groups_split_children(sleeper):
    groups = pid_groups(os.getpid(), {"vision": sleeper.pid, "suara": None, "edge": None})
    assert set(groups) == set(GROUPS)
    assert groups["utama"] == [os.getpid()]
    # python.exe venv di Windows adalah peluncur dengan satu proses anak: keduanya ikut vision
    assert groups["vision"][0] == sleeper.pid and len(groups["vision"]) >= 1
    assert not set(groups["vision"]) & set(groups["lain"])
    assert sleeper.pid not in groups["lain"] and groups["suara"] == groups["edge"] == []


def test_bus_roots_reads_worker_and_browser_pids():
    class P:
        def __init__(self, pid):
            self.pid = pid

    class Bus:
        def __init__(self):
            self.processes = {"vision": P(11), "audio": P(22)}

    class Browser:
        pid = 33

    assert bus_roots(Bus(), Browser()) == {"vision": 11, "suara": 22, "edge": 33}
    assert bus_roots(object(), None) == {"vision": None, "suara": None, "edge": None}


def test_sample_writes_numbers_only(tmp_path, sleeper):
    clock = iter([0.0, 0.0, 5.0])
    rec = ResourceRecorder(tmp_path, lambda: pid_groups(os.getpid(), {"vision": sleeper.pid}),
                           5.0, clock=lambda: next(clock),
                           wall_clock=lambda: datetime(2026, 10, 18, tzinfo=UTC))  # fmt: skip
    rec.t0 = rec.clock()
    first = rec.sample()
    second = rec.sample()
    assert [r["group"] for r in first] == list(GROUPS)
    by = {r["group"]: r for r in second}
    assert by["utama"]["n_processes"] == 1 and by["utama"]["uss_mb"] > 0
    assert by["vision"]["n_processes"] >= 1 and by["vision"]["elapsed_s"] == 5.0
    assert all(r["cpu_pct"] == 0.0 for r in first)  # CPU butuh dua sampel
    assert by["utama"]["cpu_pct"] >= 0.0
    with rec.csv_path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert list(rows[0]) == list(FIELDS) and len(rows) == 2 * len(GROUPS)
    for row in rows:  # N-08: selain ts dan nama kelompok, hanya angka
        assert row["group"] in GROUPS
        for key in ("elapsed_s", "n_processes", "cpu_pct", "uss_mb"):
            float(row[key])


def test_start_stop_writes_run_json(tmp_path):
    rec = make_recorder(tmp_path / "run", "kiosk", True, dict, interval_s=0.05,
                        info={"ui_backend": "web"})  # fmt: skip
    rec.start()
    rec.stop_event.wait(0.2)
    rec.stop()
    info = json.loads((tmp_path / "run" / "run.json").read_text(encoding="utf-8"))
    assert info["e09"] is True and info["app_mode"] == "kiosk" and info["interval_s"] == 0.05
    assert info["n_samples"] >= 1 and info["stopped_at"] and info["ui_backend"] == "web"
    assert (tmp_path / "run" / "resources.csv").is_file()


def test_invalid_interval_rejected(tmp_path):
    with pytest.raises(ValueError):
        ResourceRecorder(tmp_path, dict, 0)


def _kiosk_settings():
    s = load_settings(DEV_YAML)
    return s.model_copy(update={"app": s.app.model_copy(update={"mode": "kiosk"})})


def test_webui_run_refuses_recorder_in_kiosk_without_e09(tmp_path, capsys):
    from mica.webui.app import run

    code = run(_kiosk_settings(), no_browser=True, record_resources=tmp_path / "r")
    assert code == 2 and "--e09" in capsys.readouterr().err
    assert not (tmp_path / "r").exists()


def test_main_recorder_flags(capsys):
    ok = [check.CheckRow("config", "OK", "ok")]
    launched = []

    def launch(settings, args):
        launched.append((args.record_resources, args.resource_interval, args.e09))
        return 0

    assert entry.main(["--record-resources", "r"], check=lambda c, e: (ok, _kiosk_settings()),
                      launch=launch) == 2  # fmt: skip
    assert "--e09" in capsys.readouterr().err and launched == []
    assert entry.main(["--record-resources", "r", "--e09", "--resource-interval", "2"],
                      check=lambda c, e: (ok, _kiosk_settings()), launch=launch) == 0  # fmt: skip
    assert launched == [(Path("r"), 2.0, True)]
    s = load_settings(DEV_YAML)
    qt = s.model_copy(update={"ui": s.ui.model_copy(update={"backend": "pyside6"})})
    assert entry.main(["--record-resources", "r"], check=lambda c, e: (ok, qt),
                      launch=launch) == 2  # fmt: skip
    assert "ui.backend: web" in capsys.readouterr().err


def test_default_interval_is_trial_value():
    assert resources.DEFAULT_INTERVAL_S == 5.0
