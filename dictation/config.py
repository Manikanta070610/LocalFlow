"""Config loading (YAML)."""
from __future__ import annotations

import os
from pathlib import Path

import yaml

DEFAULTS: dict = {
    "hotkey": "Super+Alt+D",
    "server": {
        "host": "127.0.0.1",
        "port": 8000,
        "model": "phonon-2",
        "auto_start": True,
        "startup_timeout": 120,
        "extra_args": [],
    },
    "hotwords": [],
    "hotword_lambda": 2.0,
    "audio": {"sample_rate": 16000, "channels": 1, "device": None, "max_seconds": 120},
    "cleanup": {
        "strip": True,
        "collapse_whitespace": True,
        "fix_space_before_punct": True,
        "capitalize_first": False,
        "add_trailing_space": True,
    },
    "typing": {"tool": "wtype", "focus_delay_ms": 150, "also_copy_to_clipboard": True},
    "indicator": {"tray": True},
    "ipc": {
        "socket_path": "~/.cache/voice-dictation/dictation.sock",
        "pid_file": "~/.cache/voice-dictation/dictation.pid",
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: str | Path) -> dict:
    path = Path(path).expanduser()
    if not path.exists():
        return _deep_merge({}, DEFAULTS)
    with open(path, "r", encoding="utf-8") as f:
        user = yaml.safe_load(f) or {}
    cfg = _deep_merge(DEFAULTS, user)
    cfg["ipc"]["socket_path"] = os.path.expanduser(cfg["ipc"]["socket_path"])
    cfg["ipc"]["pid_file"] = os.path.expanduser(cfg["ipc"]["pid_file"])
    return cfg


def base_url(cfg: dict) -> str:
    s = cfg["server"]
    return f"http://{s['host']}:{s['port']}"
