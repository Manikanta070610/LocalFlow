"""Tray indicator: grey=idle, red=recording, yellow=transcribing.

Falls back to console lines when pystray has no system tray (common
on minimal Wayland sessions). The daemon works fine without a tray.
"""
from __future__ import annotations

import threading

STATES = ("idle", "recording", "transcribing")
COLORS = {"idle": (128, 128, 128), "recording": (220, 50, 50), "transcribing": (220, 180, 40)}


def _make_icon(color, size: int = 64):
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([6, 6, size - 6, size - 6], fill=color + (255,))
    return img


class Indicator:
    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self._state = "idle"
        self._lock = threading.Lock()
        self._icon = None
        self._images = {}
        self._usable = False
        if not enabled:
            print("[indicator] tray disabled in config; console-only.", flush=True)
            return
        try:
            import pystray  # noqa: F401
            from PIL import Image  # noqa: F401

            for name, color in COLORS.items():
                self._images[name] = _make_icon(color)
            self._usable = True
        except Exception as e:
            print(f"[indicator] tray unavailable ({e}); console-only.", flush=True)
            self._usable = False

    def start(self, on_quit=None) -> None:
        if not self._usable:
            return
        import pystray

        def quit_action(icon, item):
            icon.stop()
            if on_quit:
                on_quit()

        self._icon = pystray.Icon(
            "voice-dictation",
            self._images["idle"],
            "Dictation: idle",
            menu=pystray.Menu(pystray.MenuItem("Quit", quit_action)),
        )
        threading.Thread(target=self._icon.run, daemon=True).start()
        print("[indicator] tray icon running (grey=idle, red=recording, yellow=transcribing).", flush=True)

    def set(self, state: str) -> None:
        assert state in STATES, state
        with self._lock:
            self._state = state
        print(f"[indicator] {state}", flush=True)
        if self._icon is not None:
            try:
                self._icon.icon = self._images[state]
                self._icon.title = f"Dictation: {state}"
            except Exception:
                pass

    def stop(self) -> None:
        icon, self._icon = self._icon, None
        if icon is None:
            return
        # The xorg backend's stop() can block on a dying X connection during
        # session teardown. Never let that block shutdown: bounded join, then
        # abandon the daemon thread.
        def quiet_stop():
            try:
                icon.stop()
            except Exception:
                pass

        t = threading.Thread(target=quiet_stop, daemon=True)
        t.start()
        t.join(timeout=1.5)
        if t.is_alive():
            print("[indicator] tray backend did not stop in time — continuing shutdown.", flush=True)
