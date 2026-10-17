"""Mic capture at 16 kHz mono. Depends on sounddevice (PortAudio)."""
from __future__ import annotations

import queue
import threading
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np


@dataclass
class Recorder:
    sample_rate: int = 16000
    channels: int = 1
    device: int | str | None = None
    max_seconds: int = 120
    _frames: list = field(default_factory=list, init=False)
    _stream: Any = field(default=None, init=False)
    _stop_event: threading.Event = field(default_factory=threading.Event, init=False)

    @property
    def recording(self) -> bool:
        return self._stream is not None

    @property
    def seconds(self) -> float:
        if not self._frames:
            return 0.0
        n = sum(f.shape[0] for f in self._frames)
        return n / float(self.sample_rate)

    def start(self) -> None:
        if self.recording:
            raise RuntimeError("already recording")
        try:
            import sounddevice as sd
        except ImportError as e:
            raise RuntimeError(
                "sounddevice is not installed. Run: ~/.venv/bin/pip install -r requirements.txt "
                "(needs libportaudio2: sudo apt install libportaudio2)"
            ) from e

        # Resolve a name substring to a device index so "headset" just works.
        device = self.device
        if isinstance(device, str):
            devs = sd.query_devices()
            match = next(
                (i for i, d in enumerate(devs) if device.lower() in d["name"].lower()),
                None,
            )
            if match is None:
                names = "\n".join(f"  [{i}] {d['name']}" for i, d in enumerate(devs))
                raise RuntimeError(f"audio device {device!r} not found. Devices:\n{names}")
            device = match

        try:
            dev_info = sd.query_devices(device, "input")
        except Exception as e:
            raise RuntimeError(f"no input device: {e}") from e
        if dev_info["max_input_channels"] < 1:
            raise RuntimeError(f"device has no input channels: {dev_info['name']}")

        self._frames = []
        self._stop_event.clear()
        q: queue.Queue = queue.Queue()

        def callback(indata, frames, time, status):
            if status:
                pass  # xruns show up here; keep going
            q.put(indata.copy())

        try:
            self._stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype="int16",
                device=device,
                callback=callback,
            )
            self._stream.start()
        except Exception as e:
            self._stream = None
            raise RuntimeError(f"could not open mic ({e}). Is it used by another app?") from e

        # Drain queue in this thread's caller? No — pump in a helper thread
        # so stop() is prompt even under load.
        def pump():
            max_frames = int(self.sample_rate * self.max_seconds)
            total = 0
            while not self._stop_event.is_set():
                try:
                    chunk = q.get(timeout=0.1)
                except queue.Empty:
                    continue
                self._frames.append(chunk)
                total += chunk.shape[0]
                if total >= max_frames:
                    break

        self._pump = threading.Thread(target=pump, daemon=True)
        self._pump.start()

    def stop(self) -> np.ndarray:
        if not self.recording:
            raise RuntimeError("not recording")
        self._stop_event.set()
        stream, self._stream = self._stream, None
        try:
            stream.stop()
            stream.close()
        finally:
            self._pump.join(timeout=2.0)
        if not self._frames:
            return np.zeros((0, self.channels), dtype=np.int16)
        audio = np.concatenate(self._frames, axis=0)
        # Force exact shape: mono int16
        if audio.ndim == 1:
            audio = audio[:, None]
        return audio.astype(np.int16)

    def record_blocking(self, seconds: float) -> np.ndarray:
        """One-shot helper used by `test-mic`. Not used by the daemon."""
        self.start()
        import time

        time.sleep(seconds)
        return self.stop()


def write_wav(path: str | Path, audio: np.ndarray, sample_rate: int = 16000) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if audio.dtype != np.int16:
        audio = audio.astype(np.int16)
    channels = 1 if audio.ndim == 1 else audio.shape[1]
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(audio.tobytes())
    return path
