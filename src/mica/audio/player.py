"""M-08 Player: memutar AudioClip ke speaker lewat sounddevice (non-ADR, SDD M-08).

- start(clip) tidak memblok, sehingga kalimat berikutnya bisa disintesis selama clip diputar;
  wait() memblok sampai clip selesai atau stop() dipanggil dari thread lain.
- Tidak ada perangkat keluaran, atau pemutaran gagal saat runtime -> SpeakerUnavailable.
Audio hanya di memori (N-08).
"""

from __future__ import annotations

from typing import Any, Protocol

from mica.audio.tts import AudioClip


class SpeakerUnavailable(Exception):
    pass


class Player(Protocol):
    def start(self, clip: AudioClip) -> None: ...

    def wait(self) -> None: ...

    def stop(self) -> None: ...


def _sounddevice() -> Any:
    import sounddevice as sd

    return sd


class SounddevicePlayer:
    def __init__(self, device: int | None = None, sd: Any = None) -> None:
        self.sd = sd if sd is not None else _sounddevice()
        self.device = device
        try:
            self.sd.query_devices(device, kind="output")
        except Exception as exc:  # noqa: BLE001 - PortAudio melempar berbagai jenis error
            raise SpeakerUnavailable(f"tidak ada speaker ({exc})") from None

    def start(self, clip: AudioClip) -> None:
        try:
            self.sd.play(clip.samples, clip.sample_rate, device=self.device)
        except Exception as exc:  # noqa: BLE001 - perangkat bisa dicabut saat runtime
            raise SpeakerUnavailable(f"speaker gagal ({exc})") from None

    def wait(self) -> None:
        try:
            self.sd.wait()
        except Exception as exc:  # noqa: BLE001
            raise SpeakerUnavailable(f"speaker gagal ({exc})") from None

    def stop(self) -> None:
        self.sd.stop()
