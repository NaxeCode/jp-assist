# AGENTS.md

jp-assist is personal Linux tooling for Japanese Discord calls. `start-whisper.sh` runs whisper.cpp's `whisper-stream` and patches Discord call audio into it with `pw-link`. `tools/ja-respond.py` (English → Japanese prompt with ghost-text completions and optional VOICEVOX TTS) and `tools/ja-clip.py` (clipboard Japanese → English) talk to a local `llama-server` on `127.0.0.1:8081`. `tools/ja-launch.sh` spawns the prompt as a floating Hyprland terminal. The files are meant to be copied into a whisper.cpp checkout. `CLAUDE.md` covers building that checkout (ROCm/HIP, gfx1100).

The Python tools are stdlib-only. There is no CI. Sanity checks: `python3 -m py_compile tools/*.py`, `bash -n start-whisper.sh tools/ja-launch.sh`, `python3 tools/test_voicevox.py` (needs VOICEVOX running).

## Code Review Rules

Focus on keeping everything local and private, keeping the audio routing correct, and keeping the interactive tools from hanging or breaking the terminal. Style is not a review concern.

### Always flag (P0/P1)

- **Data leaving the machine.** Call transcripts, typed text, and clipboard contents must only go to loopback services (`LLAMA_URL` `127.0.0.1:8081`, VOICEVOX `127.0.0.1:50021`). Flag any non-loopback endpoint, cloud API, telemetry, or configurable URL that defaults to a remote host.
- **Clipboard over-collection.** `ja-clip.py` must process only text that passes `is_japanese()` (kana/kanji ranges). Flag changes that send all clipboard contents to the LLM, or that log or persist clipboard text, which can contain passwords. Clipboard text shown by `notify-send` must be passed as an argument list, never through a shell.
- **Shell or command injection.** `subprocess` calls must use argv lists (no `shell=True`) with model or clipboard text passed as data. In `ja-launch.sh`, flag interpolating anything other than the monitor name and fixed terminal commands into the `hyprctl --batch` / `dispatch exec` string.
- **Microphone capture.** `start-whisper.sh` must keep unlinking the local mic (`Scarlett Solo USB:capture_MONO`) from `SDL Application:input_MONO`, so only the remote side of the call is transcribed. Flag changes that link the mic or drop the unlink.
- **Terminal left in raw mode.** `ja-respond.py` puts the TTY in raw mode. Flag paths where `termios.tcsetattr(..., old)` isn't guaranteed (it must stay in `finally`), and background threads (debounce `Timer`, TTS) that write to stdout after `_stopped` is set or without `_render_lock`.

### Flag when relevant

- HTTP calls without a `timeout`. `ja-clip.py`'s `urlopen` currently has none, so a hung `llama-server` blocks the watcher. Flag new untimed calls. Failures from VOICEVOX or the LLM must degrade gracefully without crashing the loop.
- `start-whisper.sh`: the `cleanup` trap must still kill the background `connect_discord` loop, and binary and model existence checks must run before launch.
- Prompt changes that drop the fixed output sections (`Japanese:` line and the others) that `extract_japanese()` parses.
- New dependencies beyond the Python standard library. Keep the tools stdlib-only.

### Don't flag

- Hardcoded device names (`WEBRTC VoiceEngine`, `Scarlett Solo USB`), the gfx1100 target, and `/tmp/ja-respond.log` crash logging. These are intentional single-machine choices.
- Broad `except Exception` in `test_voicevox.py` result reporting.
