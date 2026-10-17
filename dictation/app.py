"""Daemon: toggle-to-record -> transcribe -> type. Wayland-only v1.

Hotkey model on Wayland: KDE owns the global shortcut (pynput cannot
grab keys on Wayland). The KDE shortcut runs `main.py toggle`, which
sends one byte over the daemon's Unix socket. Press once to start,
press again to stop + transcribe.

State machine: idle --toggle--> recording --toggle--> transcribing --done--> idle.
Transcription runs on a worker thread so a second toggle during
transcribing is ignored instead of deadlocking the socket loop.
"""
from __future__ import annotations

import atexit
import os
import signal
import socket
import threading
from pathlib import Path

from .audio import Recorder
from .config import base_url, load_config
from .engine import ensure_server, server_health, stop_server, transcribe_audio
from .indicator import Indicator
from .output import cleanup_text, notify, type_text

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"


class DictationDaemon:
    def __init__(self, config_path: str | Path = CONFIG_PATH):
        self.config_path = Path(config_path)
        self.cfg = load_config(self.config_path)
        self.indicator = Indicator(enabled=self.cfg.get("indicator", {}).get("tray", True))
        self.recorder = self._make_recorder()
        self.server_proc = None
        self._state = "idle"  # idle | recording | transcribing
        self._lock = threading.Lock()
        self._sock_path = self.cfg["ipc"]["socket_path"]
        self._pid_file = self.cfg["ipc"]["pid_file"]
        self._stop = threading.Event()
        self._shutdown_done = threading.Event()

    def _make_recorder(self) -> Recorder:
        a = self.cfg.get("audio", {})
        return Recorder(
            sample_rate=int(a.get("sample_rate", 16000)),
            channels=int(a.get("channels", 1)),
            device=a.get("device"),
            max_seconds=int(a.get("max_seconds", 120)),
        )

    # -- lifecycle -----------------------------------------------------
    def start(self) -> None:
        self._write_pid()
        atexit.register(self.shutdown)
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                # hard=True: session shutdown/logout must never wait on us.
                signal.signal(sig, lambda *_: self.shutdown(hard=True))
            except ValueError:
                pass  # not on main thread in tests

        print(f"[daemon] config: {self.config_path}", flush=True)
        print(f"[daemon] hotkey (KDE shortcut): {self.cfg.get('hotkey')}", flush=True)
        try:
            self.server_proc = ensure_server(self.cfg)
            h = server_health(self.cfg) or {}
            print(f"[daemon] server up: {base_url(self.cfg)} model={h.get('model')}", flush=True)
        except RuntimeError as e:
            print(f"[daemon] FATAL: {e}", flush=True)
            raise SystemExit(1) from e

        self.indicator.start(on_quit=lambda: self.shutdown(hard=True))
        self.indicator.set("idle")
        self._serve_socket()
        print("[daemon] ready. Toggle with: python main.py toggle", flush=True)
        try:
            self._stop.wait()
            # A shutdown is in progress (signal handler or tray Quit). Give a
            # non-main-thread shutdown time to finish cleanup before we exit.
            self._shutdown_done.wait(timeout=10)
        except KeyboardInterrupt:
            pass
        finally:
            self.shutdown()

    def shutdown(self, hard: bool = False) -> None:
        """Best-effort fast shutdown. `hard` guarantees process exit (signal
        handlers, tray Quit): during session shutdown the tray backend can
        block forever, so every step is bounded and we never rely on it."""
        if self._stop.is_set():
            if hard:
                os._exit(0)
            return
        self._stop.set()
        with self._lock:
            state, self._state = self._state, "idle"
        if state == "recording":
            try:
                self.recorder.stop()
            except Exception:
                pass
        try:
            self.indicator.set("idle")
        except Exception:
            pass
        try:
            self.indicator.stop()
        except Exception:
            pass
        stop_server(self.server_proc)
        self.server_proc = None
        srv = getattr(self, "_srv", None)
        if srv is not None:
            try:
                srv.close()
            except Exception:
                pass
        for p in (self._sock_path, self._pid_file):
            try:
                Path(p).unlink(missing_ok=True)
            except Exception:
                pass
        print("[daemon] stopped.", flush=True)
        self._shutdown_done.set()
        if hard:
            os._exit(0)

    # -- IPC -----------------------------------------------------------
    def _write_pid(self) -> None:
        Path(self._pid_file).parent.mkdir(parents=True, exist_ok=True)
        Path(self._pid_file).write_text(str(os.getpid()))

    def _serve_socket(self) -> None:
        Path(self._sock_path).parent.mkdir(parents=True, exist_ok=True)
        try:
            Path(self._sock_path).unlink(missing_ok=True)
        except Exception:
            pass
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(self._sock_path)
        srv.listen(5)
        srv.settimeout(0.5)
        self._srv = srv

        def loop():
            while not self._stop.is_set():
                try:
                    conn, _ = srv.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                with conn:
                    try:
                        conn.recv(64)
                    except Exception:
                        pass
                    threading.Thread(target=self.toggle, daemon=True).start()

        threading.Thread(target=loop, daemon=True).start()

    # -- core ----------------------------------------------------------
    def toggle(self) -> str:
        with self._lock:
            state = self._state
        if state == "idle":
            return self._start_recording()
        if state == "recording":
            return self._stop_and_transcribe()
        print("[daemon] busy (transcribing) — toggle ignored.", flush=True)
        return "busy"

    def _start_recording(self) -> str:
        try:
            self.recorder.start()
        except RuntimeError as e:
            print(f"[daemon] mic error: {e}", flush=True)
            notify("Dictation: no mic", str(e)[:200])
            return "mic-error"
        with self._lock:
            self._state = "recording"
        self.indicator.set("recording")
        print("[daemon] recording… toggle again to stop.", flush=True)
        # Auto-stop guard so a forgotten toggle doesn't grow unbounded.
        # daemon=True: a pending timer must never block interpreter exit
        # (this caused 90 s shutdown hangs before).
        timer = threading.Timer(self.recorder.max_seconds, self._auto_stop)
        timer.daemon = True
        timer.start()
        return "recording"

    def _auto_stop(self) -> None:
        with self._lock:
            still = self._state == "recording"
        if still:
            print("[daemon] max_seconds reached — auto-stopping.", flush=True)
            self._stop_and_transcribe()

    def _stop_and_transcribe(self) -> str:
        try:
            audio = self.recorder.stop()
        except RuntimeError as e:
            print(f"[daemon] stop error: {e}", flush=True)
            with self._lock:
                self._state = "idle"
            self.indicator.set("idle")
            return "stop-error"
        with self._lock:
            self._state = "transcribing"
        self.indicator.set("transcribing")
        print(f"[daemon] recorded {len(audio) / self.recorder.sample_rate:.1f}s, transcribing…", flush=True)
        threading.Thread(target=self._transcribe_and_type, args=(audio,), daemon=True).start()
        return "transcribing"

    def _transcribe_and_type(self, audio) -> None:
        try:
            # Reload config per utterance so hotword edits need no restart.
            try:
                self.cfg = load_config(self.config_path)
            except Exception:
                pass
            raw = transcribe_audio(self.cfg, audio, self.recorder.sample_rate)
            text = cleanup_text(raw or "", self.cfg)
            if not text.strip():
                print("[daemon] empty transcript — nothing typed.", flush=True)
                notify("Dictation", "Heard nothing — try again.")
            else:
                print(f"[daemon] transcript: {text!r}", flush=True)
                where = type_text(self.cfg, text)
                if where == "clipboard":
                    notify("Dictation: pasted to clipboard", "Typing failed — press Ctrl+V.")
        except RuntimeError as e:
            print(f"[daemon] transcription failed: {e}", flush=True)
            notify("Dictation failed", str(e)[:200])
        finally:
            with self._lock:
                self._state = "idle"
            self.indicator.set("idle")


def send_toggle(cfg_path: str | Path = CONFIG_PATH) -> str:
    """Called by the KDE shortcut. Exits non-zero when the daemon is absent."""
    cfg = load_config(cfg_path)
    sock = cfg["ipc"]["socket_path"]
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.connect(sock)
    except (FileNotFoundError, ConnectionRefusedError):
        print(f"[toggle] daemon not running (no socket at {sock}). Start it first.", flush=True)
        raise SystemExit(2)
    with s:
        s.sendall(b"toggle\n")
    print("[toggle] sent.", flush=True)
    return "sent"
