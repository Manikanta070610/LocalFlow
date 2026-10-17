<div align="center">

# 🎙️ LocalFlow

**Local, private voice dictation for Linux — without the cloud.**

Press a key. Talk. Press it again. The words land in whatever app has focus.

*No account · No subscription · No audio ever leaves your machine*

![Platform](https://img.shields.io/badge/platform-Linux%20%C2%B7%20Wayland-1793D1?logo=linux&logoColor=white)
![Privacy](https://img.shields.io/badge/privacy-100%25%20local-2ea44f)
![Cloud](https://img.shields.io/badge/cloud-none-critical)
![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)
![STT](https://img.shields.io/badge/STT-Phonon--2%20%C2%B7%20CPU-ff8c00)
![License](https://img.shields.io/badge/license-Apache--2.0-blue)

</div>

```
  press Super+Alt+D            🎙  recording      (tray ● red)
  speak naturally              ⏳  transcribing   (tray ● yellow)
  press Super+Alt+D
  ───────────────────────────────────────────────────────────────
  Hey team, the design review moved to Friday.   ← at your cursor
```

<!-- Tip: record a 10-second demo (OBS/SimpleScreenRecorder) and drop it
     in here as docs/demo.gif — nothing sells this app like seeing it type. -->

> **TL;DR** — `git clone … && bash setup.sh`, bind one keyboard shortcut, start dictating.
> First run downloads a ~160 MB speech model; after that it's fully offline.

Inspired by Wispr Flow — built for people who'd rather their voice never leave the desktop.

---

## Why this exists

Cloud dictation is a monthly fee and a microphone in someone else's data center. This is the opposite:

- 🏠 **Local by construction** — mic → your CPU → clipboard → your cursor. The only network request the app ever makes is the one-time speech-model download. Airplane mode test: it still types.
- 💸 **Free, and not "free tier"** — no accounts, no telemetry, no per-word pricing. A cloud dictation habit runs ~$10–15/month.
- ⌨️ **Types where you already are** — browser, IDE, chat, terminal. It inserts with a **kernel-level Ctrl+V** (`/dev/uinput`), which works on KDE and GNOME, where most input-injection tricks simply fail.
- 🐧 **A native Wayland citizen** — no X11 hacks, no keyloggers, no background daemons you didn't ask for. One service, owned by your user account.

## This app vs. cloud dictation

|                              | **Voice Dictation**          | Cloud dictation apps      |
| ---------------------------- | ---------------------------- | ------------------------- |
| Price                        | **Free**                     | ~$10–15 / month           |
| Audio uploads                | **Never**                    | Every utterance           |
| Works offline                | **Yes**¹                     | No                        |
| Account required             | **No**                       | Usually                   |
| Runs on                      | Linux · Wayland              | macOS / Windows / web     |

¹ After the one-time model download.

## Features

- 🎯 **Toggle from anywhere** — one desktop shortcut starts and stops recording; you never leave the app you're typing in.
- ⌨️ **Triple-redundant insertion** — kernel-level Ctrl+V via `/dev/uinput` (KDE ✅, GNOME ✅) → `wtype` on compositors that support it → clipboard as the always-works fallback, with a notification instead of an error.
- 🔊 **Self-managed local STT** — the daemon spawns `phonon serve` (Phonon-2, CPU) when needed and takes it down with the service. No orphan processes to babysit.
- 🎛️ **Tray indicator** — grey idle / red recording / yellow transcribing, with a console fallback.
- ✍️ **Hotwords & cleanup** — bias the model toward your project names and jargon (per utterance); automatic whitespace, punctuation and capitalization cleanup.
- 🔌 **Everything in one config file** — mic device, port, timeouts, paste keys (`ctrl+shift+v` for terminals), hotwords.
- 🧯 **Instant, clean shutdown** — bounded stops and a hard `TimeoutStopSec=5` promise: stopping the service never hangs your logout or shutdown.
- 📦 **One-command install** — one script handles apt/dnf/pacman/zypper, venv, `phonon`, `/dev/uinput` permissions and autostart.

## Requirements

- Linux with a **Wayland** session — KDE Plasma, GNOME, Sway, Hyprland, … (X11 works clipboard-only)
- Python 3.10+, any modern 64-bit CPU — **no GPU needed**
- ~1.5 GB disk (PyTorch dominates: ~800 MB; model: ~160 MB, fetched on first run)
- One-time `sudo` during install (distro packages + a `/dev/uinput` udev rule) and a single relogin if you get added to the `input` group
- A microphone 🎤

## Install

```bash
git clone https://github.com/Manikanta070610/LocalFlow.git
cd LocalFlow
bash setup.sh
```

The installer is idempotent — safe to re-run. It:

1. installs system packages via your package manager (apt/dnf/pacman/zypper)
   — `wl-clipboard`, `portaudio`, `wtype`, `python3-venv`
2. creates/reuses a Python venv and installs the app deps; if `phonon` isn't
   on the machine it pip-installs `fermion-research` (the STT engine) too
3. runs the root helper (`setup-uinput.sh`) so the `input` group can write
   `/dev/uinput` — and makes it survive reboots
4. installs autostart: a systemd user service, or an XDG autostart entry
   where there's no systemd user manager
5. smoke-tests the phonon server (first run downloads the ~160 MB model)

Options: `--venv PATH`, `--no-phonon`, `--no-uinput`, `--no-service`.
Venv default: `$VD_VENV`, else `~/.venv` when it already contains `phonon`,
else `<repo>/.venv`.

### Bind the toggle key

| Desktop  | Where                                                                    | Command                                              |
| -------- | ------------------------------------------------------------------------ | ---------------------------------------------------- |
| KDE      | System Settings → Keyboard → Shortcuts → Add New → Command or Script      | `<venv>/bin/python <repo>/main.py toggle`            |
| GNOME    | Settings → Keyboard → Custom Shortcuts                                    | same                                                 |
| Sway     | `~/.config/sway/config`                                                   | `bindsym $mod+d exec <venv>/bin/python <repo>/main.py toggle` |
| Hyprland | `~/.config/hypr/hyprland.conf`                                            | `bind = SUPER ALT, D, exec, <venv>/bin/python <repo>/main.py toggle` |

Suggested key: `Super+Alt+D` (or F9). `python main.py setup-help` prints this
with your real paths.

## Daily use

1. Click into any text field (cursor blinking).
2. Press the toggle key → tray turns **red** → speak.
3. Press it again → tray turns **yellow** → the words appear at the cursor.

Dictating into a terminal? Terminals paste with Ctrl+Shift+V — set
`paste_keys: "ctrl+shift+v"` in `config.yaml` and restart the service.

## How it works

```
hotkey (your desktop's shortcut) ──> main.py toggle ──> Unix socket ──> daemon
                                                                         │
 focus stays in your app        ┌───────────────────────────────────────┘
 ▼                              ▼
sounddevice records mic     phonon serve          cleanup            wl-copy
16 kHz mono in RAM   ─wav──> /v1/audio/     ─text──> strip/        ──> clipboard
                                      transcriptions  spaces  ──> + Ctrl+V via
                                                                 /dev/uinput
tray: grey idle / red recording / yellow transcribing (+ journalctl logs)
```

Two Wayland facts shape the design: no app can grab a global hotkey (the
compositor owns input), so the hotkey is a desktop shortcut that runs
`main.py toggle`; and some compositors (KWin, GNOME) have no
virtual-keyboard protocol, so pasting uses a **kernel-level Ctrl+V via
`/dev/uinput`** instead of keystroke injection. Insertion priority:
uinput auto-paste → `wtype` (where supported) → clipboard + Ctrl+V.

Your audio never touches the network: it's held in RAM, and a temporary WAV
is written only for the localhost REST call to `phonon serve` — then deleted
immediately.

## Configuration (`config.yaml`)

| Key | Meaning |
| --- | --- |
| `hotkey` | Docs only (the real binding lives in your desktop's shortcuts) |
| `server.*` | `phonon serve` management: port, model, auto_start, timeouts, extra flags |
| `hotwords` (≤25), `hotword_lambda` | Sent per-request as multipart fields — bias the model toward your names/jargon |
| `audio.device` | `null` = default mic; int index or name substring (`"headset"`) |
| `cleanup.*` | strip / collapse whitespace / fix space-before-punct / capitalize / trailing space |
| `typing.tool` | `"wtype"` tries wtype after uinput; `"clipboard"` skips it |
| `typing.auto_paste / paste_keys / paste_delay_ms` | uinput Ctrl+V (primary path); `ctrl+shift+v` for terminals |
| `typing.focus_delay_ms / also_copy_to_clipboard` | settle delay; keep a clipboard backup |

`hotwords`/`cleanup`/`typing` are re-read per utterance; `audio`/`ipc`/
`indicator`/`server` changes need `systemctl --user restart voice-dictation`.

## FAQ

**Does my audio leave the machine?**
No. Recording, transcription and cleanup are local. The one-time model
download is the app's only network request. Audio lives in RAM; a temp WAV
exists only during the localhost transcription call.

**Which desktops are supported?**
Any Wayland session with custom shortcuts — KDE, GNOME, Sway, Hyprland, …
Reference-tested on Debian 13 + KDE Plasma 6.3. On X11 the app still
transcribes, but can only put the text on your clipboard.

**Why does the installer need sudo?**
Exactly two things: distro packages, and the `/dev/uinput` permissions that
enable kernel-level pasting (udev rule + `input` group). Runtime is fully
unprivileged; `--no-uinput` skips that step.

**How fast is it?**
Transcription is CPU-local — typically a second or two after you stop
speaking for a normal sentence, with no network round-trip.

**How much disk does it take?**
~1.5 GB installed, mostly PyTorch (~800 MB) plus the ~160 MB model.

**What doesn't it do yet?**
Hold-to-talk mode, multi-language models, X11 auto-paste, Windows/macOS.
Issues and PRs are welcome.

## Troubleshooting

Logs: `journalctl --user -u voice-dictation -f`; the phonon server log lives
next to the socket (`~/.cache/voice-dictation/phonon-serve.log`).

| Symptom | Cause → fix |
| --- | --- |
| manual `toggle` works, key does nothing | shortcut not applied / key conflict → re-check desktop settings |
| `toggle`: `daemon not running`, exit 2 | service stopped → `systemctl --user start voice-dictation` |
| `wtype ... non-zero exit status` | compositor lacks virtual-keyboard protocol (KWin/GNOME) → keep `typing.auto_paste: true` (default) |
| `cannot open /dev/uinput` / auto-paste text in log | perms or module → `bash setup.sh` (or repair: `sudo bash setup-uinput.sh`), then relogin if it says so |
| `empty transcript — nothing typed` | silence → speak closer/louder, check `test-mic` peak |
| stray words from noise/music | STT hallucinates on non-speech → re-record a clear sentence |
| machine shutdown hangs / app survives logout | should not happen: bounded stops + `TimeoutStopSec=5`; if it does, send logs |
| text only in clipboard, no paste | terminal app? set `paste_keys: "ctrl+shift+v"` |

## Verify the install (5 minutes)

Run from the repo, replacing `python` with your venv python:

| Step | Command | Pass criterion |
| --- | --- | --- |
| Mic | `main.py test-mic --secs 3` | WAV saved, peak well above 0.02 |
| Server | `main.py test-server` | `/health` ok, model reported |
| Transcribe | `main.py test-transcribe FILE.wav` | text + cleaned variant printed |
| Paste path | `main.py test-type` | `typed` (or `clipboard` + `wl-paste` shows text) |
| Daemon loop | `daemon` + `toggle` ×2 | red → yellow → idle; text pasted |
| Shutdown | `systemctl --user stop voice-dictation` | exits in < 1 s, `phonon` gone |

No microphone handy? This transcribes a bundled sample and should print
`She had your duck suit and greasy wash water all year.`:

```bash
curl -sL -o /tmp/sample.wav https://raw.githubusercontent.com/mozilla/DeepSpeech/master/data/smoke_test/LDC93S1.wav
python main.py test-transcribe /tmp/sample.wav
```

<details>
<summary><b>Project layout</b> (click to expand)</summary>

```
LocalFlow/
├── setup.sh                     # universal installer (any distro/desktop)
├── setup-uinput.sh              # root helper: /dev/uinput perms + module at boot
├── config.yaml                  # server, hotwords, audio, cleanup, typing
├── requirements.txt             # pip deps (installed into your venv)
├── main.py                      # daemon | toggle | test-mic | test-server |
│                                # test-transcribe | test-type | setup-help
├── dictation/
│   ├── config.py                # YAML load + defaults
│   ├── audio.py                 # mic @ 16 kHz mono (sounddevice), WAV writer
│   ├── engine.py                # start/stop phonon serve, REST client
│   ├── output.py                # cleanup + uinput/wtype/clipboard insertion
│   ├── autopaste.py             # Ctrl+V via evdev UInput
│   ├── indicator.py             # pystray tray, console fallback
│   └── app.py                   # daemon: toggle → record → transcribe → paste
└── systemd/
    └── voice-dictation.service  # template for manual installs (setup.sh generates one)
```

</details>

## License

Apache-2.0 — see [LICENSE](LICENSE).

## Credits

- **Speech engine:** [Phonon](https://fermionresearch.com) by Fermion Research
  (`pip install fermion-research`) — the local CPU STT that makes this possible.
- **Built with:** `sounddevice`/PortAudio (mic capture), `evdev`
  (`/dev/uinput` Ctrl+V), `wl-clipboard` + `wtype` (Wayland insertion),
  `pystray`/Pillow (tray), and a small pure-Python daemon that ties it together.
- Reference desktop: Debian 13 + KDE Plasma 6.3.

⭐ If this saves you from a dictation subscription, star the
[repo](https://github.com/Manikanta070610/LocalFlow) and tell a friend with
a mechanical keyboard.
