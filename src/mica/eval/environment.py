"""M-12: info lingkungan untuk run.json (reprodusibilitas N-14 dan konteks pengukuran latensi)."""

from __future__ import annotations

import os
import platform
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from mica.kb.index import package_version, torch_version


def _run(args: list[str], cwd: Path | None = None) -> str | None:
    try:
        out = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=10, check=True)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout


def git_commit(cwd: Path | None = None) -> str | None:
    out = _run(["git", "rev-parse", "HEAD"], cwd)
    if out is None:
        return None
    return out.strip() or None


def git_dirty(cwd: Path | None = None) -> bool | None:
    """True bila ada perubahan belum di-commit (termasuk file baru) di luar results/.

    None bila bukan repo git atau git tidak tersedia.
    """
    top = _run(["git", "rev-parse", "--show-toplevel"], cwd)
    if top is None:
        return None
    status = _run(
        [
            "git",
            "status",
            "--porcelain",
            "--untracked-files=normal",
            "--",
            ".",
            ":(exclude)results",
        ],
        Path(top.strip()),
    )
    return None if status is None else bool(status.strip())


def power_status() -> dict[str, Any] | None:
    """Sumber daya (AC/baterai) lewat GetSystemPowerStatus; None di luar Windows."""
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    class SystemPowerStatus(ctypes.Structure):
        _fields_ = [
            ("ACLineStatus", wintypes.BYTE),
            ("BatteryFlag", wintypes.BYTE),
            ("BatteryLifePercent", wintypes.BYTE),
            ("SystemStatusFlag", wintypes.BYTE),
            ("BatteryLifeTime", wintypes.DWORD),
            ("BatteryFullLifeTime", wintypes.DWORD),
        ]

    status = SystemPowerStatus()
    if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)):
        return None
    ac = status.ACLineStatus & 0xFF
    percent = status.BatteryLifePercent & 0xFF
    return {
        "source": {0: "battery", 1: "ac"}.get(ac, "unknown"),
        "battery_percent": None if percent == 255 else percent,
        "battery_saver": bool(status.SystemStatusFlag & 0xFF),
    }


_SCHEME = re.compile(r"([0-9a-fA-F-]{36})\s*\((.*)\)")


def power_plan() -> dict[str, Any] | None:
    """Power plan aktif dari `powercfg /getactivescheme`; None di luar Windows."""
    if sys.platform != "win32":
        return None
    out = _run(["powercfg", "/getactivescheme"])
    if out is None:
        return None
    text = out.strip()
    match = _SCHEME.search(text)
    return {
        "guid": match.group(1).lower() if match else None,
        "name": match.group(2).strip() if match else None,
        "raw": text,
    }


def torch_threads() -> int | None:
    try:
        import torch
    except ImportError:
        return None
    return int(torch.get_num_threads())


def collect_environment(cwd: Path | None = None) -> dict[str, Any]:
    return {
        "python": platform.python_version(),
        "torch": torch_version(),
        "torch_num_threads": torch_threads(),
        "sentence_transformers": package_version("sentence-transformers"),
        "platform": platform.platform(),
        "cpu": platform.processor(),
        "cpu_count_logical": os.cpu_count(),
        "power": power_status(),
        "power_plan": power_plan(),
        "git_commit": git_commit(cwd),
        "git_dirty": git_dirty(cwd),
    }


def dirty_warning(environment: dict[str, Any]) -> str | None:
    if not environment.get("git_dirty"):
        return None
    return (
        "peringatan: ada perubahan belum di-commit di luar results/ "
        f"(git_commit {environment.get('git_commit')}); hasil ini tidak terikat ke satu commit"
    )
