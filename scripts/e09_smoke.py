"""Uji asap alat E-09 (bukan hasil E-09): perekam sumber daya + log giliran + eval latency.

python scripts/e09_smoke.py [--config config/dev.yaml] [--questions 10] [--out results/E-09]
    [--interval 1]

1. Menyalin config ke folder sementara dengan logging.dir di folder itu (log uji tidak
   bercampur dengan logs/).
2. Menjalankan `python -m mica.webui --config <salinan> --fake-workers --fake-pipeline
   --record-resources <folder>` sebagai proses terpisah (Edge kiosk ikut terbuka).
3. Pengendali (pengganti bench in-process, karena UI berjalan di proses lain) tersambung ke
   WebSocket UI seperti browser dan mengirim N pertanyaan ketik generik "pertanyaan uji N"
   berurutan, masing-masing ditunggu sampai jawabannya tampil dan status kembali READY.
4. Menutup Edge, sehingga server, controller, dan perekam berhenti rapi.
5. Menjalankan eval latency (--tool-test) pada log dan CSV sumber daya, lalu menyalin
   resources.csv dan run.json perekam ke folder hasil (resources/).
Wajib daya AC.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import yaml

QUESTION = "pertanyaan uji {n}"
TIMEOUT_S = 60.0  # non-ADR: batas tunggu satu tahap


def wait_url(proc: subprocess.Popen) -> str:
    assert proc.stdout is not None
    deadline = time.time() + TIMEOUT_S
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            raise RuntimeError(f"mica.webui berhenti (kode {proc.poll()})")
        if line.startswith("MICA web: "):
            return line.removeprefix("MICA web: ").strip()
    raise TimeoutError("URL MICA web tidak muncul")


def ask_all(url: str, n_questions: int) -> int:
    from simple_websocket import Client

    origin = url.rstrip("/")
    ws = Client.connect(origin.replace("http://", "ws://") + "/ws", headers={"Origin": origin})
    view = None
    asked = 0
    try:
        deadline = time.time() + TIMEOUT_S * n_questions
        while time.time() < deadline:
            raw = ws.receive(timeout=TIMEOUT_S)
            if raw is None:
                break
            msg = json.loads(raw)
            if msg.get("type") != "view":
                continue
            view = msg["view"]
            answered = sum(m["role"] == "mica" for m in view["messages"])
            ready = view["status"] in ("IDLE", "READY") and view["send_enabled"]
            if answered >= asked and ready:
                if asked == n_questions:
                    break
                asked += 1
                ws.send(json.dumps({"type": "text", "text": QUESTION.format(n=asked)}))
    finally:
        ws.close()
    return asked


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python scripts/e09_smoke.py")
    parser.add_argument("--config", type=Path, default=Path("config/dev.yaml"))
    parser.add_argument("--questions", type=int, default=10)
    parser.add_argument("--out", type=Path, default=Path("results/E-09"))
    parser.add_argument("--interval", type=float, default=1.0,
                        help="interval perekam untuk uji asap (detik)")  # fmt: skip
    args = parser.parse_args(argv)

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import psutil
    import ui_bench

    from mica.eval.latency import run_latency

    try:
        power = ui_bench.require_ac()
    except ui_bench.NotOnAc as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    work = Path(tempfile.mkdtemp(prefix="mica-e09-smoke-"))
    raw = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    raw["logging"]["dir"] = str(work / "logs")
    config = work / "config.yaml"
    config.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")
    rec_dir = work / "resources"
    cmd = [sys.executable, "-m", "mica.webui", "--config", str(config), "--fake-workers",
           "--fake-pipeline", "--record-resources", str(rec_dir),
           "--resource-interval", str(args.interval)]  # fmt: skip
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                            encoding="utf-8")  # fmt: skip
    try:
        url = wait_url(proc)
        time.sleep(3.0)  # Edge tersambung dan layar pertama tampil
        asked = ask_all(url, args.questions)
        print(f"pertanyaan terkirim dan terjawab: {asked}", flush=True)
        time.sleep(2.0 * args.interval)  # beberapa sampel perekam setelah pertanyaan terakhir
        # tutup Edge (seperti pengguna menutup jendela): server dan perekam berhenti rapi
        browsers = []
        for child in psutil.Process(proc.pid).children(recursive=True):
            try:
                if child.name().lower() == "msedge.exe" and not any(
                    a.startswith("--type=") for a in child.cmdline()
                ):
                    browsers.append(child)
            except psutil.NoSuchProcess:
                continue
        for browser in browsers:
            try:
                browser.terminate()
            except psutil.NoSuchProcess:
                pass
        proc.wait(timeout=TIMEOUT_S)
    finally:
        if proc.poll() is None:
            proc.kill()
    run_dir, overall = run_latency(work / "logs", args.out, "smoke", rec_dir / "resources.csv",
                                   tool_test=True)  # fmt: skip
    shutil.copytree(rec_dir, run_dir / "resources")
    info = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    info.update({
        "smoke": {"command": " ".join(Path(c).name if i == 0 else c for i, c in enumerate(cmd))
                  .replace(str(work), "<folder sementara>"),
                  "questions_requested": args.questions, "questions_answered": asked,
                  "driver": "scripts/e09_smoke.py (WebSocket seperti browser)",
                  "power": power, "exit_code_webui": proc.returncode},
        "log_dir": "folder sementara (log uji tidak di-commit)",
        "resources": {"path": "resources/resources.csv",
                      "sha256": info["resources"]["sha256"]},
    })  # fmt: skip
    (run_dir / "run.json").write_text(json.dumps(info, ensure_ascii=False, indent=1) + "\n",
                                      encoding="utf-8")  # fmt: skip
    shutil.rmtree(work, ignore_errors=True)
    print(f"keseluruhan (uji alat): {overall}")
    print(f"tersimpan: {run_dir.as_posix()}")
    return 0 if asked == args.questions and proc.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
