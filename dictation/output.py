"""Text cleanup (local) + typing into the focused Wayland app."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import time

_WS_RUN = re.compile(r"\s+")
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([.,!?;:])")


def cleanup_text(text: str, cfg: dict) -> str:
    c = cfg.get("cleanup", {})
    if c.get("strip", True):
        text = text.strip()
    if c.get("collapse_whitespace", True):
        text = _WS_RUN.sub(" ", text)
    if c.get("fix_space_before_punct", True):
        text = _SPACE_BEFORE_PUNCT.sub(r"\1", text)
    if c.get("capitalize_first", False) and text:
        text = text[0].upper() + text[1:]
    if c.get("add_trailing_space", True) and text and not text.endswith(" "):
        text += " "
    return text


def session_type() -> str:
    return os.environ.get("XDG_SESSION_TYPE", "unknown")


def type_text(cfg: dict, text: str) -> str:
    """Insert text into the focused app. Returns 'typed' | 'clipboard'.

    Priority: (1) wl-copy + synthetic Ctrl+V via uinput — works on every
    Wayland compositor, incl. KWin; (2) wtype for compositors that have the
    virtual-keyboard protocol; (3) clipboard only, with a notice.
    """
    if not text:
        return "typed"
    stype = session_type()
    tcfg = cfg.get("typing", {})
    if stype != "wayland":
        copy_to_clipboard(text)
        print(f"[typer] XDG_SESSION_TYPE={stype} (not Wayland) — copied to clipboard instead.", flush=True)
        return "clipboard"

    delay = int(tcfg.get("focus_delay_ms", 150))
    if delay > 0:
        time.sleep(delay / 1000.0)

    errors: list[str] = []

    # 1) kernel-level Ctrl+V via /dev/uinput (default, compositor-agnostic)
    if tcfg.get("auto_paste", False):
        from .autopaste import send_paste

        copy_to_clipboard(text)
        try:
            send_paste(
                keys=tcfg.get("paste_keys", "ctrl+v"),
                pre_delay=int(tcfg.get("paste_delay_ms", 250)) / 1000.0,
            )
            return "typed"
        except Exception as e:
            errors.append(f"uinput auto-paste: {e}")

    # 2) wtype (skipped when typing.tool is "clipboard")
    if tcfg.get("tool", "wtype") != "clipboard":
        wtype = shutil.which("wtype")
        if wtype is None:
            errors.append("wtype not installed")
        else:
            try:
                subprocess.run([wtype, "--", text], check=True, timeout=15)
                if tcfg.get("also_copy_to_clipboard", True):
                    try:
                        copy_to_clipboard(text)
                    except Exception:
                        pass
                return "typed"
            except subprocess.CalledProcessError as e:
                errors.append(f"wtype: {e}")

    # 3) clipboard fallback
    copy_to_clipboard(text)
    detail = "; ".join(errors) if errors else "typing tools disabled"
    print(f"[typer] {detail} — text is on the clipboard, press Ctrl+V.", flush=True)
    return "clipboard"


def copy_to_clipboard(text: str) -> None:
    wl_copy = shutil.which("wl-copy")
    if wl_copy is None:
        raise RuntimeError("wl-copy not found (sudo apt install wl-clipboard).")
    subprocess.run([wl_copy], input=text.encode("utf-8"), check=True, timeout=10)


def notify(title: str, body: str) -> None:
    ns = shutil.which("notify-send")
    if ns is None:
        return
    try:
        subprocess.run([ns, title, body], timeout=5)
    except Exception:
        pass
