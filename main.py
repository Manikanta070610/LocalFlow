#!/usr/bin/env python3
"""Voice dictation entry point (Wayland-only v1).

Usage:
  python main.py daemon                       # run tray daemon (server auto-starts)
  python main.py toggle                       # KDE shortcut calls this (start/stop)
  python main.py test-mic [--secs 3]          # Step 1: mic -> /tmp/dictation-test.wav
  python main.py test-server                  # Step 2a: is phonon serve healthy?
  python main.py test-transcribe FILE.wav     # Step 2b: file -> text
  python main.py test-type [--text "hi"]      # Step 3: type into focused app
  python main.py setup-help                    # KDE shortcut + autostart instructions
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from dictation.app import CONFIG_PATH, DictationDaemon, send_toggle  # noqa: E402
from dictation.config import base_url, load_config  # noqa: E402

CONFIG = str(CONFIG_PATH)


def cmd_daemon(args) -> int:
    DictationDaemon(args.config).start()
    return 0


def cmd_toggle(args) -> int:
    send_toggle(args.config)
    return 0


def cmd_test_mic(args) -> int:
    from dictation.audio import Recorder, write_wav

    cfg = load_config(args.config)
    a = cfg["audio"]
    rec = Recorder(a["sample_rate"], a["channels"], a["device"], max_seconds=args.secs + 2)
    print(f"[test-mic] recording {args.secs}s @ {a['sample_rate']}Hz mono — speak now…", flush=True)
    try:
        audio = rec.record_blocking(args.secs)
    except RuntimeError as e:
        print(f"[test-mic] FAIL: {e}")
        return 1
    out = write_wav("/tmp/dictation-test.wav", audio, rec.sample_rate)
    peak = (abs(audio).max() / 32768.0) if audio.size else 0.0
    print(f"[test-mic] saved {out} ({rec.seconds:.1f}s, peak={peak:.2f})", flush=True)
    if peak < 0.02:
        print("[test-mic] WARN: near-silence. Wrong mic? Set audio.device in config.yaml.", flush=True)
        return 2
    print("[test-mic] OK. Play it: paplay /tmp/dictation-test.wav", flush=True)
    return 0


def cmd_test_server(args) -> int:
    from dictation.engine import ensure_server, server_health

    cfg = load_config(args.config)
    h = server_health(cfg)
    if h is not None:
        print(f"[test-server] OK: {base_url(cfg)} model={h.get('model')} version={h.get('version')}")
        return 0
    print(f"[test-server] down at {base_url(cfg)} — starting `phonon serve` …", flush=True)
    try:
        proc = ensure_server(cfg)
        print("[test-server] OK (server started)." + (" (was already up)" if proc is None else ""))
        if proc is not None:
            proc.terminate()  # test only; the daemon owns the real one
        return 0
    except RuntimeError as e:
        print(f"[test-server] FAIL: {e}")
        return 1


def cmd_test_transcribe(args) -> int:
    from dictation.engine import ensure_server, transcribe_wav
    from dictation.output import cleanup_text

    cfg = load_config(args.config)
    try:
        ensure_server(cfg)
    except RuntimeError as e:
        print(f"[test-transcribe] FAIL: {e}")
        return 1
    print(f"[test-transcribe] sending {args.wav} …", flush=True)
    try:
        raw = transcribe_wav(cfg, args.wav)
    except RuntimeError as e:
        print(f"[test-transcribe] FAIL: {e}")
        return 1
    print(f"[test-transcribe] raw:      {raw!r}")
    print(f"[test-transcribe] cleaned:  {cleanup_text(raw, cfg)!r}")
    return 0


def cmd_test_type(args) -> int:
    from dictation.output import session_type, type_text

    cfg = load_config(args.config)
    print(f"[test-type] XDG_SESSION_TYPE={session_type()}. Focus a text field — typing in 2s…", flush=True)
    import time

    time.sleep(2)
    where = type_text(cfg, args.text)
    print(f"[test-type] result: {where} (clipboard = fallback worked, press Ctrl+V).")
    return 0


SETUP_HELP = """\
Toggle key (the global hotkey — bind it in your desktop's settings):

  Command: {venv_py} {root}/main.py toggle      (suggested key: {hotkey})

  KDE:      System Settings > Keyboard > Shortcuts > Add New > Command or Script
  GNOME:    Settings > Keyboard > Custom Shortcuts
  Sway:     bindsym $mod+d exec {venv_py} {root}/main.py toggle
  Hyprland: bind = SUPER ALT, D, exec, {venv_py} {root}/main.py toggle

Autostart (recommended): re-run the installer, it is idempotent:
  bash {root}/setup.sh

Manual (systemd user unit — adjust paths in the file if yours differ):
  cp {root}/systemd/voice-dictation.service ~/.config/systemd/user/
  systemctl --user daemon-reload
  systemctl --user enable --now voice-dictation
  journalctl --user -u voice-dictation -f
"""


def cmd_setup_help(args) -> int:
    import os

    print(SETUP_HELP.format(hotkey=load_config(args.config).get("hotkey"), venv_py=sys.executable, root=ROOT))
    print(f"XDG_SESSION_TYPE={os.environ.get('XDG_SESSION_TYPE')}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Local voice dictation (phonon, Wayland)")
    p.add_argument("--config", default=CONFIG)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("daemon").set_defaults(fn=cmd_daemon)
    sub.add_parser("toggle").set_defaults(fn=cmd_toggle)
    m = sub.add_parser("test-mic")
    m.add_argument("--secs", type=int, default=3)
    m.set_defaults(fn=cmd_test_mic)
    sub.add_parser("test-server").set_defaults(fn=cmd_test_server)
    t = sub.add_parser("test-transcribe")
    t.add_argument("wav")
    t.set_defaults(fn=cmd_test_transcribe)
    t2 = sub.add_parser("test-type")
    t2.add_argument("--text", default="hello from voice dictation ")
    t2.set_defaults(fn=cmd_test_type)
    sub.add_parser("setup-help").set_defaults(fn=cmd_setup_help)
    args = p.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
