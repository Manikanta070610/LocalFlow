#!/usr/bin/env bash
# ============================================================================
# Root part of the voice-dictation install: make /dev/uinput usable by the
# 'input' group at every boot (kernel-level Ctrl+V for auto-paste).
#
#   sudo bash setup-uinput.sh
#
# setup.sh calls this automatically; run it directly to repair a broken
# setup. Needs a terminal (sudo must be able to prompt for your password).
# Idempotent; safe to re-run. Works with or without systemd.
# ============================================================================
set -u

if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: run as root:  sudo bash $0" >&2
    exit 1
fi

TARGET_USER="${SUDO_USER:-}"

echo "==> 1/6 ensure the 'input' group exists"
getent group input >/dev/null || groupadd input

if [ -n "$TARGET_USER" ] && [ "$TARGET_USER" != "root" ]; then
    if id -nG "$TARGET_USER" | grep -qw input; then
        echo "    $TARGET_USER already in 'input'"
    else
        usermod -aG input "$TARGET_USER" && echo "    added $TARGET_USER to 'input' (relogin required)"
    fi
fi

echo "==> 2/6 load the uinput module at every boot"
if [ -d /etc/modules-load.d ]; then
    echo uinput > /etc/modules-load.d/uinput.conf
else
    echo "    /etc/modules-load.d missing (non-systemd?) — loading module for this boot only"
fi

echo "==> 3/6 udev rule with static_node (right group/mode at boot)"
if [ -d /etc/udev/rules.d ]; then
    cat > /etc/udev/rules.d/99-uinput.rules <<'EOF'
KERNEL=="uinput", GROUP="input", MODE="0660", OPTIONS+="static_node=uinput"
EOF
else
    echo "    /etc/udev/rules.d missing — skipping udev rule"
fi

echo "==> 4/6 reload udev rules"
command -v udevadm >/dev/null && udevadm control --reload-rules || echo "    udevadm not present — skipped"

echo "==> 5/6 load the module now"
if command -v modprobe >/dev/null; then
    modprobe uinput && echo "    modprobe uinput: OK" \
        || echo "    modprobe uinput: FAILED — paste the error above"
else
    echo "    modprobe not found — skipped"
fi

echo "==> 6/6 enforce perms on the current node"
if [ -e /dev/uinput ]; then
    chown root:input /dev/uinput 2>/dev/null
    chmod 0660 /dev/uinput 2>/dev/null
else
    echo "    /dev/uinput does not exist yet (will appear when the module loads)"
fi

echo
echo "==> state now:"
ls -la /dev/uinput 2>&1 || true
if grep -q uinput /proc/misc 2>/dev/null; then
    echo "driver:  loaded ($(grep uinput /proc/misc))"
else
    echo "driver:  NOT loaded"
fi
