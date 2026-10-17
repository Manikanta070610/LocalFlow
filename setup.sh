#!/usr/bin/env bash
# ============================================================================
# voice-dictation installer — local push-to-talk dictation for ANY Linux
# desktop on Wayland (KDE, GNOME, Sway, Hyprland, ...). CPU-only, fully local.
#
#   bash setup.sh [options]
#
# Options:
#   --venv PATH    python venv to use (default: $VD_VENV, else ~/.venv when it
#                  already has phonon, else <repo>/.venv)
#   --no-phonon    don't pip-install fermion-research (point config.yaml at an
#                  already-running phonon server instead)
#   --no-uinput    skip the root-level /dev/uinput setup (no auto-paste;
#                  wtype/clipboard still work)
#   --no-service   skip autostart (systemd user unit / XDG autostart)
#   -h, --help     this text
#
# Run as your normal user. sudo is used only for system packages and the
# uinput root steps; it will prompt for your password in this terminal.
# ============================================================================
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="${VD_VENV:-}"
WITH_PHONON=1
WITH_UINPUT=1
WITH_SERVICE=1

while [ $# -gt 0 ]; do
    case "$1" in
        --venv)       VENV="$2"; shift 2 ;;
        --no-phonon)  WITH_PHONON=0; shift ;;
        --no-uinput)  WITH_UINPUT=0; shift ;;
        --no-service) WITH_SERVICE=0; shift ;;
        -h|--help)    sed -n '3,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown option: $1 (try --help)" >&2; exit 2 ;;
    esac
done

say()  { printf '\n==> %s\n' "$*"; }
have() { command -v "$1" >/dev/null 2>&1; }
SUDO=""
if [ "$(id -u)" -ne 0 ] && have sudo; then SUDO="sudo"; fi

# ---------------------------------------------------------------- preflight
say "Preflight"
[ "$(uname -s)" = "Linux" ] || { echo "ERROR: Linux only." >&2; exit 1; }
have python3 || { echo "ERROR: python3 not found. Install python3 (3.10+)." >&2; exit 1; }
python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)' \
    || { echo "ERROR: python 3.10+ required, found $(python3 -c 'import sys;print(sys.version.split()[0])')." >&2; exit 1; }
SESSION="${XDG_SESSION_TYPE:-unknown}"
if [ "$SESSION" != "wayland" ]; then
    echo "WARNING: XDG_SESSION_TYPE=$SESSION (not Wayland)."
    echo "         Wayland is the supported target; on X11 text will only reach the clipboard."
fi
for tool in wl-copy wtype; do
    have "$tool" || echo "NOTE: $tool not found yet (will install or degrade gracefully)."
done

# ----------------------------------------------------------------- packages
say "System packages"
if have apt-get; then
    $SUDO apt-get install -y --no-install-recommends wl-clipboard libportaudio2 python3-venv \
        || echo "  apt failed — install manually: wl-clipboard libportaudio2 python3-venv"
    $SUDO apt-get install -y wtype || echo "  (wtype unavailable — fine, uinput auto-paste is the primary path)"
elif have dnf; then
    $SUDO dnf install -y wl-clipboard portaudio \
        || echo "  dnf failed — install manually: wl-clipboard portaudio"
    $SUDO dnf install -y wtype || echo "  (wtype unavailable in your repos — fine)"
elif have pacman; then
    $SUDO pacman -S --needed --noconfirm wl-clipboard portaudio wtype \
        || echo "  pacman failed — install manually: wl-clipboard portaudio wtype"
elif have zypper; then
    $SUDO zypper --non-interactive install wl-clipboard portaudio wtype \
        || echo "  zypper failed — install manually: wl-clipboard portaudio wtype"
else
    echo "  Unknown package manager. Needed: wl-clipboard (clipboard), portaudio (mic), optional wtype."
fi

# --------------------------------------------------------------------- venv
say "Python environment"
if [ -z "$VENV" ]; then
    if [ -x "$HOME/.venv/bin/phonon" ]; then VENV="$HOME/.venv"; else VENV="$REPO/.venv"; fi
fi
echo "  venv: $VENV"
if [ ! -d "$VENV" ]; then
    python3 -m venv "$VENV" || { echo "ERROR: venv creation failed (install python3-venv)." >&2; exit 1; }
fi
PYBIN="$VENV/bin/python"
"$PYBIN" -m pip install --upgrade pip >/dev/null
echo "  installing requirements.txt ..."
"$PYBIN" -m pip install -r "$REPO/requirements.txt"
# ------------------------------------------------- phonon (the STT engine)
# `phonon` is the CLI of the pip package `fermion-research`. The daemon looks
# for it in its own venv first, so install it THERE when missing.
PHONON_BIN="$VENV/bin/phonon"
PVER="$("$PYBIN" -m pip show fermion-research 2>/dev/null | awk '/^Version:/{print $2; exit}' || true)"
if [ -x "$PHONON_BIN" ]; then
    echo "  phonon found: $PHONON_BIN ${PVER:+($PVER)}"
elif [ "$WITH_PHONON" -eq 0 ]; then
    if have phonon; then
        echo "  phonon on PATH: $(command -v phonon) — not in the venv (--no-phonon), daemon will use it if service PATH allows"
    else
        echo "  WARNING: no phonon anywhere, and --no-phonon given. Set server.port in config.yaml to an existing server."
    fi
else
    if have phonon; then
        echo "  phonon found on PATH ($(command -v phonon)) but not in the venv — installing into the venv so the service can always find it ..."
    else
        echo "  phonon not present on this device — installing it (pulls torch; the ~160 MB model downloads on first server start) ..."
    fi
    echo "  running: $PYBIN -m pip install --upgrade fermion-research"
    "$PYBIN" -m pip install --upgrade fermion-research || \
        echo "  ERROR: install failed. Manual retry: $PYBIN -m pip install fermion-research   (needs internet; torch is several GB on disk)"
    if [ -x "$PHONON_BIN" ]; then
        echo "  phonon installed: $PHONON_BIN $("$PYBIN" -m pip show fermion-research 2>/dev/null | awk '/^Version:/{print "(" $2 ")"; exit}')"
    else
        echo "  WARNING: fermion-research did not produce $PHONON_BIN — check the pip output above."
        echo "           Workaround: re-run with --no-phonon and point config.yaml at an existing phonon server."
    fi
fi

# ------------------------------------------------------------------- uinput
if [ "$WITH_UINPUT" -eq 1 ]; then
    say "uinput access (kernel-level Ctrl+V for auto-paste)"
    if [ -w /dev/uinput ] && grep -q uinput /proc/misc 2>/dev/null; then
        echo "  already OK"
    elif [ -z "$SUDO" ] && [ "$(id -u)" -ne 0 ]; then
        echo "  no sudo available — run later as root: sudo bash $REPO/setup-uinput.sh"
    else
        bash "$REPO/setup-uinput.sh" 2>&1 | sed 's/^/  /' || true
        if ! id -nG | grep -qw input; then
            echo "  NOTE: you were added to the 'input' group — LOG OUT and back in once for it to apply."
        fi
        if [ -w /dev/uinput ]; then echo "  /dev/uinput writable — OK"
        else echo "  /dev/uinput still not writable now; after relogin it will be. Repair: sudo bash $REPO/setup-uinput.sh"; fi
    fi
fi

# ---------------------------------------------------------------- autostart
# (component check runs BEFORE this, so no daemon is running to race with)

# -------------------------------------------------------------------- check
say "Component check (server)"
echo "  first run may take a while (model download ~160 MB)"
( cd "$REPO" && "$PYBIN" main.py test-server ) || \
    echo "  test-server failed above — fix that before dictating."

if [ "$WITH_SERVICE" -eq 1 ]; then
    say "Autostart"
    if have systemctl && systemctl --user show-environment >/dev/null 2>&1; then
        UNIT_DIR="$HOME/.config/systemd/user"
        mkdir -p "$UNIT_DIR"
        ENV_LINE=""
        [ "$SESSION" = "wayland" ] && ENV_LINE="Environment=XDG_SESSION_TYPE=wayland"
        cat > "$UNIT_DIR/voice-dictation.service" <<EOF
[Unit]
Description=Voice dictation daemon (phonon, Wayland)
After=graphical-session.target pipewire.service
PartOf=graphical-session.target

[Service]
ExecStart=$PYBIN $REPO/main.py daemon
Restart=on-failure
RestartSec=3
$ENV_LINE
# Session shutdown must never wait on the tray backend or the phonon child.
TimeoutStopSec=5

[Install]
WantedBy=default.target
EOF
        systemctl --user daemon-reload
        systemctl --user enable --now voice-dictation
        echo "  systemd user service installed and started."
        echo "  logs: journalctl --user -u voice-dictation -f"
    else
        AUTOSTART="$HOME/.config/autostart/voice-dictation.desktop"
        mkdir -p "$(dirname "$AUTOSTART")"
        cat > "$AUTOSTART" <<EOF
[Desktop Entry]
Type=Application
Name=Voice Dictation
Comment=Local push-to-talk dictation daemon
Exec=$PYBIN $REPO/main.py daemon
EOF
        echo "  no systemd user manager — wrote XDG autostart: $AUTOSTART"
    fi
fi

cat <<EOF

$(printf '=%.0s' {1..72})
Almost done. Final steps:

1) Bind the toggle key in your desktop's keyboard settings
   command:   $PYBIN $REPO/main.py toggle   (suggested key: Super+Alt+D)
     KDE:    System Settings > Keyboard > Shortcuts > Add New > Command or Script
     GNOME:  Settings > Keyboard > Custom Shortcuts
     Sway:   bindsym \$mod+d exec $PYBIN $REPO/main.py toggle
     Hyprland: bind = SUPER ALT, D, exec, $PYBIN $REPO/main.py toggle

2) Dictate: focus a text field, press the key, speak, press it again.
$(printf '=%.0s' {1..72})
EOF
