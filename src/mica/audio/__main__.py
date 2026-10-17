"""CLI audio M-08, hanya untuk mode dev.

python -m mica.audio fetch-voice [--config config/dev.yaml] [--voices-dir models/piper]
    unduh suara Piper dari Hugging Face rhasspy/piper-voices pada revisi commit yang dikunci,
    verifikasi sha256 setiap file.
python -m mica.audio say "<teks>" | --file <txt> [--no-play] [--device N] [--list-devices]
    [--rate --out <folder>]
    sintesis tiap baris (satu kalimat per baris), cetak teks asli, hasil normalisasi, synth_s,
    durasi audio, RTF, dan first_audio_s, lalu putar lewat sounddevice. --rate meminta nilai di
    terminal setelah tiap baris diputar dan menulis ratings.csv + run.json.

Audio tidak pernah ditulis ke disk (N-08); --rate hanya menulis teks dan angka.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import sys
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mica.audio.normalize import normalize_for_speech
from mica.audio.tts import (
    DEFAULT_VOICES_DIR,
    AudioClip,
    PiperTts,
    TextToSpeech,
    VoiceMissing,
    concat,
    voice_path,
)
from mica.config import ConfigError, Settings, load_settings

DEFAULT_CONFIG = Path("config/dev.yaml")
# Suara ADR-11 pada revisi rhasspy/piper-voices yang dikunci (main per 17 Okt 2026, diambil dari
# https://huggingface.co/api/models/rhasspy/piper-voices); sha256 diukur saat unduhan pertama.
HF_REPO = "rhasspy/piper-voices"
HF_REVISION = "c10ece1aade47bb51c153c893d14e5bf8e5b7117"
VOICE = "id_ID-news_tts-medium"
VOICE_REPO_DIR = "id/id_ID/news_tts/medium"
VOICE_SHA256 = {
    f"{VOICE}.onnx": "ed8f02aa593f7af6b19acbdb8142e0da0dd72f46194eb33d38e0eb10a52597e8",
    f"{VOICE}.onnx.json": "1ef677072668a5e172e0759b1d3871f129009d1167f093325a17607f7add5ad7",
}
RATING_LABELS = {
    "1": "jelas dan angka/singkatan benar",
    "2": "angka atau singkatan salah dibaca",
    "3": "suara tidak jelas/tidak wajar",
}
RATING_FIELDS = (
    "no", "teks", "teks_normal", "synth_s", "audio_s", "rtf", "first_audio_s", "nilai", "label",
)  # fmt: skip


class AudioCliError(Exception):
    pass


def _require_dev(settings: Settings, command: str) -> None:
    if settings.app.mode != "dev":
        raise AudioCliError(f"{command} hanya boleh dijalankan saat app.mode: dev")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


# --- fetch-voice ------------------------------------------------------------------------


def voice_url(name: str) -> str:
    return f"https://huggingface.co/{HF_REPO}/resolve/{HF_REVISION}/{VOICE_REPO_DIR}/{name}"


def _download(url: str, dest: Path) -> None:
    import httpx

    with httpx.stream("GET", url, follow_redirects=True, timeout=120) as r:
        r.raise_for_status()
        with dest.open("wb") as f:
            for block in r.iter_bytes(1 << 20):
                f.write(block)


def cmd_fetch_voice(
    settings: Settings,
    voices_dir: Path,
    download: Callable[[str, Path], None] = _download,
) -> int:
    _require_dev(settings, "fetch-voice")
    if settings.audio.tts.voice != VOICE:
        raise AudioCliError(
            f"audio.tts.voice {settings.audio.tts.voice!r} tidak punya revisi terkunci; "
            f"fetch-voice hanya untuk {VOICE}"
        )
    voices_dir = Path(voices_dir)
    voices_dir.mkdir(parents=True, exist_ok=True)
    print(f"{HF_REPO} revisi {HF_REVISION}")
    for name, expected in VOICE_SHA256.items():
        dest = voices_dir / name
        if dest.is_file() and sha256_file(dest) == expected:
            print(f"{dest.as_posix()} sudah ada, sha256 cocok")
            continue
        part = dest.with_name(dest.name + ".part")
        download(voice_url(name), part)
        actual = sha256_file(part)
        if actual != expected:
            part.unlink()
            raise AudioCliError(f"sha256 {name} tidak cocok: {actual} (harus {expected})")
        part.replace(dest)
        print(f"{dest.as_posix()} sha256 {actual} (cocok)")
    return 0


# --- say --------------------------------------------------------------------------------


@dataclass(frozen=True)
class LineResult:
    text: str
    normal: str
    clip: AudioClip
    synth_s: float
    first_audio_s: float

    @property
    def rtf(self) -> float:
        return self.synth_s / self.clip.duration_s if self.clip.duration_s > 0 else 0.0


def synthesize_line(
    tts: TextToSpeech, text: str, clock: Callable[[], float] = time.perf_counter
) -> LineResult:
    """first_audio_s = waktu sampai clip kalimat pertama siap; synth_s = total sintesis."""
    start = clock()
    first: float | None = None
    clips: list[AudioClip] = []
    for clip in tts.stream(text):
        if first is None:
            first = clock() - start
        clips.append(clip)
    joined = concat(clips)
    return LineResult(text, normalize_for_speech(text), joined, joined.synth_s, first or 0.0)


def _play(clip: AudioClip, device: int | None) -> None:
    import sounddevice as sd

    sd.play(clip.samples, clip.sample_rate, device=device)
    sd.wait()


def _read_lines(args: argparse.Namespace) -> list[str]:
    if args.file is not None:
        lines = Path(args.file).read_text(encoding="utf-8-sig").splitlines()
        return [line.strip() for line in lines if line.strip()]
    if args.text:
        return [args.text]
    raise AudioCliError('beri teks ("say <teks>") atau --file <txt>')


def _ask_rating(play: Callable[[], None], ask: Callable[[str], str]) -> str:
    prompt = (
        "nilai: "
        + " | ".join(f"{k} = {v}" for k, v in RATING_LABELS.items())
        + " | r = putar ulang > "
    )
    while True:
        answer = ask(prompt).strip().lower()
        if answer in RATING_LABELS:
            return answer
        if answer == "r":
            play()


def _run_info(tts_voice_file: Path) -> dict[str, Any]:
    from mica.eval.environment import git_commit, git_dirty, power_plan, power_status
    from mica.kb.index import package_version

    config_file = Path(f"{tts_voice_file}.json")
    return {
        "component": "tts",
        "experiment": "E-06",
        "git_commit": git_commit(),
        "git_dirty": git_dirty(),
        "piper_tts": package_version("piper-tts"),
        "onnxruntime": package_version("onnxruntime"),
        "num2words": package_version("num2words"),
        "sounddevice": package_version("sounddevice"),
        "voice": {
            "name": tts_voice_file.stem,
            "hf_repo": HF_REPO,
            "hf_revision": HF_REVISION,
            "onnx_sha256": sha256_file(tts_voice_file),
            "onnx_json_sha256": sha256_file(config_file),
        },
        "python": platform.python_version(),
        "platform": platform.platform(),
        "cpu": platform.processor(),
        "power": power_status(),
        "power_plan": power_plan(),
    }


def _fmt(r: LineResult) -> str:
    return (
        f"synth_s {r.synth_s:.3f} | audio_s {r.clip.duration_s:.3f} | RTF {r.rtf:.3f} | "
        f"first_audio_s {r.first_audio_s:.3f}"
    )


def cmd_say(
    args: argparse.Namespace,
    settings: Settings,
    tts_factory: Callable[[Path, float | None], TextToSpeech] = PiperTts,
    play: Callable[[AudioClip, int | None], None] = _play,
    ask: Callable[[str], str] = input,
    clock: Callable[[], float] = time.perf_counter,
) -> int:
    _require_dev(settings, "say")
    if args.rate and args.out is None:
        raise AudioCliError("--rate butuh --out <folder>")
    if args.rate and args.no_play:
        raise AudioCliError("--rate butuh pemutaran; jangan pakai --no-play")
    lines = _read_lines(args)
    out_dir = Path(args.out) if args.rate else None
    if out_dir is not None and (out_dir / "ratings.csv").exists():
        raise AudioCliError(f"{(out_dir / 'ratings.csv').as_posix()} sudah ada; pakai folder baru")

    tts_cfg = settings.audio.tts
    path = voice_path(tts_cfg.voice, args.voices_dir)
    t0 = clock()
    tts = tts_factory(path, tts_cfg.length_scale)
    length = "bawaan suara" if tts_cfg.length_scale is None else tts_cfg.length_scale
    print(f"suara {path.as_posix()} | length_scale {length} | muat {clock() - t0:.2f} s")

    rows: list[dict[str, Any]] = []
    for no, text in enumerate(lines, start=1):
        result = synthesize_line(tts, text, clock)
        print(f"[{no}] {text}")
        print(f"    normal: {result.normal}")
        print(f"    {_fmt(result)}")
        if not args.no_play:
            play(result.clip, args.device)
        if out_dir is not None:
            value = _ask_rating(lambda r=result: play(r.clip, args.device), ask)
            rows.append(
                {
                    "no": no,
                    "teks": text,
                    "teks_normal": result.normal,
                    "synth_s": f"{result.synth_s:.3f}",
                    "audio_s": f"{result.clip.duration_s:.3f}",
                    "rtf": f"{result.rtf:.3f}",
                    "first_audio_s": f"{result.first_audio_s:.3f}",
                    "nilai": value,
                    "label": RATING_LABELS[value],
                }
            )
    if out_dir is not None:
        write_ratings(out_dir, rows, _run_info(path) if path.is_file() else {"voice": None})
        print(
            f"tersimpan: {(out_dir / 'ratings.csv').as_posix()}, {(out_dir / 'run.json').as_posix()}"
        )
    return 0


def write_ratings(out_dir: Path, rows: Iterable[dict[str, Any]], info: dict[str, Any]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "ratings.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=RATING_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    (out_dir / "run.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )


def cmd_list_devices() -> int:
    import sounddevice as sd

    print(sd.query_devices())
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m mica.audio")
    sub = parser.add_subparsers(dest="command", required=True)

    fetch = sub.add_parser("fetch-voice", help="unduh suara Piper terkunci ke models/piper (dev)")
    fetch.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    fetch.add_argument("--voices-dir", type=Path, default=DEFAULT_VOICES_DIR)

    say = sub.add_parser("say", help="sintesis dan putar teks, ukur waktu (dev saja)")
    say.add_argument("text", nargs="?", help="teks yang dibacakan")
    say.add_argument("--file", type=Path, help="file teks, satu kalimat per baris")
    say.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    say.add_argument("--voices-dir", type=Path, default=DEFAULT_VOICES_DIR)
    say.add_argument("--no-play", action="store_true", help="ukur saja, tanpa memutar")
    say.add_argument("--device", type=int, help="indeks perangkat keluaran sounddevice")
    say.add_argument("--list-devices", action="store_true", help="tampilkan perangkat audio")
    say.add_argument("--rate", action="store_true", help="minta nilai 1/2/3 setelah tiap baris")
    say.add_argument("--out", type=Path, help="folder ratings.csv dan run.json (dengan --rate)")
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    args = build_parser().parse_args(argv)
    try:
        if args.command == "say" and args.list_devices:
            return cmd_list_devices()
        settings = load_settings(args.config)
        if args.command == "fetch-voice":
            return cmd_fetch_voice(settings, args.voices_dir)
        return cmd_say(args, settings)
    except (ConfigError, AudioCliError, VoiceMissing) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
