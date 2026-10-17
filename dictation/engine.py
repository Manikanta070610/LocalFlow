"""Local phonon server management + REST transcription client.

Server API (v0.2.11): POST /v1/audio/transcriptions (multipart),
GET /health. `hotwords` is a per-request form field — the server
binary has NO --hotwords flag (only `phonon transcribe` does).
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests

from .audio import write_wav
from .config import base_url


def server_health(cfg: dict) -> dict | None:
    try:
        r = requests.get(base_url(cfg) + "/health", timeout=3)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def find_phonon() -> str | None:
    """phonon binary from the daemon's own venv, then PATH, then ~/.venv."""
    candidates = [Path(sys.executable).with_name("phonon")]
    which = shutil.which("phonon")
    if which:
        candidates.append(Path(which))
    candidates.append(Path(os.path.expanduser("~/.venv/bin/phonon")))
    for c in candidates:
        if c.exists():
            return str(c)
    return None


def ensure_server(cfg: dict) -> subprocess.Popen | None:
    """Start `phonon serve` if /health is down. Returns the child or None if already up."""
    if server_health(cfg) is not None:
        return None
    if not cfg["server"].get("auto_start", True):
        raise RuntimeError(
            f"phonon server is down at {base_url(cfg)} and auto_start=false. "
            f"Start it: phonon serve --port {cfg['server']['port']}"
        )
    phonon = find_phonon()
    if not phonon:
        raise RuntimeError("phonon binary not found (looked in PATH and ~/.venv/bin/phonon).")
    port = str(cfg["server"]["port"])
    cmd = [phonon, "serve", "--port", port, *cfg["server"].get("extra_args", [])]
    log = Path(cfg["ipc"]["socket_path"]).parent / "phonon-serve.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    fh = open(log, "ab")
    proc = subprocess.Popen(cmd, stdout=fh, stderr=subprocess.STDOUT, start_new_session=True)
    deadline = time.time() + float(cfg["server"].get("startup_timeout", 120))
    last_err = ""
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"`{' '.join(cmd)}` exited early (code {proc.returncode}). See {log}")
        h = server_health(cfg)
        if h is not None:
            return proc
        time.sleep(1.0)
    # One last check before failing (model warm-up can be slow on CPU).
    try:
        proc.terminate()
    except Exception:
        pass
    raise RuntimeError(f"phonon serve did not become healthy in time. See {log}. {last_err}")


def stop_server(proc: subprocess.Popen | None, timeout: float = 3.0) -> None:
    """SIGTERM the phonon serve process group, SIGKILL it if it lingers."""
    if proc is None or proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except Exception:
        try:
            proc.terminate()
        except Exception:
            return
    try:
        proc.wait(timeout=timeout)
        return
    except Exception:
        pass
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def transcribe_wav(cfg: dict, wav_path: str | Path, timeout: int = 120) -> str:
    """POST a wav file, return raw text. Raises RuntimeError with a clear cause."""
    url = base_url(cfg) + "/v1/audio/transcriptions"
    data: dict = {"model": cfg["server"]["model"]}
    hotwords = cfg.get("hotwords") or []
    if hotwords:
        data["hotwords"] = ", ".join(hotwords)
        try:
            data["hotword_lambda"] = str(float(cfg.get("hotword_lambda", 2.0)))
        except Exception:
            pass
    try:
        with open(wav_path, "rb") as f:
            files = {"file": (Path(wav_path).name, f, "audio/wav")}
            r = requests.post(url, files=files, data=data, timeout=timeout)
    except requests.ConnectionError as e:
        raise RuntimeError(
            f"cannot reach transcription server at {url} (is `phonon serve` running?). {e}"
        ) from e
    if r.status_code == 404:
        raise RuntimeError(f"server 404 — wrong model name? cfg model={data['model']!r}. {r.text[:200]}")
    if r.status_code >= 400:
        raise RuntimeError(f"server error {r.status_code}: {r.text[:300]}")
    ctype = r.headers.get("content-type", "")
    if "text/plain" in ctype:
        return r.text
    try:
        return r.json().get("text", "")
    except Exception as e:
        raise RuntimeError(f"bad server response: {r.text[:200]}") from e


def transcribe_audio(cfg: dict, audio, sample_rate: int = 16000) -> str:
    """Transcribe an int16 numpy array via a temp wav (REST needs a file part)."""
    import numpy as np

    audio = np.asarray(audio)
    if audio.size == 0:
        return ""
    with tempfile.NamedTemporaryFile(suffix=".wav", prefix="dictation-", delete=False) as tf:
        tmp = tf.name
    try:
        write_wav(tmp, audio, sample_rate)
        return transcribe_wav(cfg, tmp)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def cli_check(argv: list[str]) -> int:
    print(f"Python {sys.version.split()[0]}", flush=True)
    return 0
