"""Auto-paste via /dev/uinput (evdev). Works on any Wayland compositor,
including KWin, which lacks the virtual-keyboard protocol wtype needs.

Flow: text is already on the clipboard (wl-copy); we emit a synthetic
Ctrl+V (or Ctrl+Shift+V for terminals) so it lands in the focused app.

Needs: /dev/uinput writable (udev rule + `input` group, relogin once).
"""
from __future__ import annotations

import os
import time

_COMBOS = {
    "ctrl+v": ("KEY_LEFTCTRL", "KEY_V"),
    "ctrl+shift+v": ("KEY_LEFTCTRL", "KEY_LEFTSHIFT", "KEY_V"),
}


def send_paste(keys: str = "ctrl+v", pre_delay: float = 0.25) -> None:
    combo = _COMBOS.get(keys.lower())
    if combo is None:
        raise ValueError(f"paste_keys must be one of {sorted(_COMBOS)}; got {keys!r}")
    try:
        from evdev import UInput, ecodes as e
    except ImportError as ex:
        raise RuntimeError("evdev not installed: ~/.venv/bin/pip install evdev") from ex
    codes = [getattr(e, name) for name in combo]
    try:
        ui = UInput({e.EV_KEY: codes}, name="voice-dictation-paste", version=0x1)
    except Exception as ex:
        try:
            st = os.stat("/dev/uinput")
            state = f"/dev/uinput is mode {oct(st.st_mode & 0o777)} {st.st_uid}:{st.st_gid}"
        except OSError as ex2:
            state = f"/dev/uinput stat failed: {ex2}"
        raise RuntimeError(
            f"{ex} — {state}. Needs: 99-uinput.rules with GROUP=\"input\", MODE=\"0660\", "
            'OPTIONS+="static_node=uinput"; user in `input` group (relogin after usermod); '
            "uinput module loadable (`sudo modprobe uinput`; add it to /etc/modules-load.d/)"
        ) from ex
    try:
        if pre_delay > 0:
            time.sleep(pre_delay)
        for c in codes:  # press down in order …
            ui.write(e.EV_KEY, c, 1)
        ui.syn()
        time.sleep(0.05)
        for c in reversed(codes):  # … release in reverse
            ui.write(e.EV_KEY, c, 0)
        ui.syn()
    finally:
        ui.close()
