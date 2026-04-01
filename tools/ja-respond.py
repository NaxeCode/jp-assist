#!/usr/bin/env python3
# Floating terminal translation tool: English → Japanese with breakdown + TTS.
# Uses raw terminal mode for full control over ghost-text rendering.
#
# Usage:
#   python3 tools/ja-respond.py
#
# Requires:
#   llama-server on port 8081  →  llama-ja
#   VOICEVOX Engine on port 50021  →  voicevox

import json
import subprocess
import sys
import termios
import threading
import tty
import urllib.parse
import urllib.request
from urllib.error import URLError

LLAMA_URL     = "http://127.0.0.1:8081/v1/chat/completions"
VOICEVOX_URL  = "http://127.0.0.1:50021"
VOICEVOX_SPEAKER = 1  # 1 = Zundamon. Run `curl localhost:50021/speakers` to browse.

TRANSLATE_SYSTEM = (
    "You are a Japanese translation assistant. "
    "Respond only in the exact format requested. No extra commentary."
)

TRANSLATE_PROMPT = """Translate '{text}' to Japanese.

Format your response exactly like this:
Japanese: <kanji/kana>
Romaji: <romanized pronunciation>
Literal: <word-for-word back-translation>
Natural: <natural English equivalent>

Breakdown:
- <word or particle>: <meaning and grammatical role>"""

COMPLETE_SYSTEM = (
    "The user is typing an English sentence. "
    "Reply with ONLY the words needed to complete it — not the full sentence, just the missing part. "
    "Under 10 words. No punctuation at the end."
)

RESET      = "\033[0m"
GREY       = "\033[2;37m"
CLEAR_LINE = "\r\033[K"


# ── LLM ───────────────────────────────────────────────────────────────────────

def _post(messages, max_tokens=512, stream=False, temperature=0.2):
    payload = json.dumps({
        "messages": messages,
        "stream": stream,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "cache_prompt": True,
    }).encode()
    req = urllib.request.Request(
        LLAMA_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    return urllib.request.urlopen(req, timeout=10)


def stream_translate(text: str) -> str:
    """Stream translation to stdout and return the full accumulated output."""
    messages = [
        {"role": "system", "content": TRANSLATE_SYSTEM},
        {"role": "user",   "content": TRANSLATE_PROMPT.format(text=text)},
    ]
    tokens = []
    try:
        with _post(messages, stream=True) as resp:
            for raw in resp:
                line = raw.decode().strip()
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data == "[DONE]":
                    break
                chunk = json.loads(data)
                token = chunk["choices"][0]["delta"].get("content", "")
                tokens.append(token)
                print(token, end="", flush=True)
    except URLError:
        print("\nError: llama-server not running. Start with: llama-ja", file=sys.stderr)
    return "".join(tokens)


def _fetch_completion(text: str) -> str:
    messages = [
        {"role": "system", "content": COMPLETE_SYSTEM},
        {"role": "user",   "content": text},
    ]
    try:
        with _post(messages, max_tokens=20, stream=False, temperature=0.3) as resp:
            result = json.loads(resp.read())
            completion = result["choices"][0]["message"]["content"].strip()
            if completion.lower().startswith(text.lower()):
                completion = completion[len(text):].lstrip()
            return completion
    except Exception:
        return ""


# ── TTS ───────────────────────────────────────────────────────────────────────

def extract_japanese(output: str) -> str:
    """Pull the kanji/kana line out of the translation output."""
    for line in output.splitlines():
        if line.startswith("Japanese:"):
            return line[len("Japanese:"):].strip()
    return ""


def speak_japanese(text: str):
    """Send text to VOICEVOX and play the resulting WAV via paplay."""
    if not text:
        return
    try:
        # Step 1 — audio_query: get synthesis parameters
        params = urllib.parse.urlencode({"text": text, "speaker": VOICEVOX_SPEAKER})
        req = urllib.request.Request(
            f"{VOICEVOX_URL}/audio_query?{params}",
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            query = json.loads(resp.read())

        # Step 2 — synthesis: get WAV bytes
        payload = json.dumps(query).encode()
        req2 = urllib.request.Request(
            f"{VOICEVOX_URL}/synthesis?speaker={VOICEVOX_SPEAKER}",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req2, timeout=30) as resp:
            wav = resp.read()

        # Step 3 — play through PipeWire via paplay
        proc = subprocess.Popen(
            ["paplay", "--stream-name=ja-respond", "-"],
            stdin=subprocess.PIPE,
        )
        proc.stdin.write(wav)
        proc.stdin.close()
        proc.wait()

    except Exception:
        pass  # silent fail — TTS is optional, don't crash if VOICEVOX is off


def _speak_async(text: str):
    """Fire-and-forget TTS in a daemon thread."""
    threading.Thread(target=speak_japanese, args=[text], daemon=True).start()


# ── Input widget ──────────────────────────────────────────────────────────────

class GhostInput:
    DEBOUNCE = 0.4
    PROMPT   = "English: "

    def __init__(self, on_replay=None):
        self.typed             = ""
        self._suggestion       = ""
        self._fetch_target     = ""
        self._timer: threading.Timer | None = None
        self._lock        = threading.Lock()
        self._render_lock = threading.Lock()
        self._on_replay   = on_replay   # callable invoked by Ctrl+P

    # ── Rendering ─────────────────────────────────────────────────────────────

    def _render(self, background: bool = False):
        if background:
            acquired = self._render_lock.acquire(blocking=False)
            if not acquired:
                return
        else:
            self._render_lock.acquire()

        try:
            with self._lock:
                suggestion = self._suggestion
                target     = self._fetch_target

            ghost = suggestion if (suggestion and target == self.typed) else ""

            sys.stdout.write(CLEAR_LINE)
            sys.stdout.write(f"{RESET}{self.PROMPT}{self.typed}")
            if ghost:
                sys.stdout.write(f"{GREY}{ghost}{RESET}")
                sys.stdout.write(f"\033[{len(ghost)}D")
            sys.stdout.flush()
        finally:
            self._render_lock.release()

    # ── Suggestion fetching ───────────────────────────────────────────────────

    def _schedule_fetch(self):
        if self._timer:
            self._timer.cancel()
        text = self.typed
        with self._lock:
            self._suggestion   = ""
            self._fetch_target = text
        if text.strip():
            self._timer = threading.Timer(self.DEBOUNCE, self._fetch, args=[text])
            self._timer.daemon = True
            self._timer.start()

    def _fetch(self, text: str):
        completion = _fetch_completion(text)
        with self._lock:
            if self._fetch_target == text:
                self._suggestion = completion
        self._render(background=True)

    # ── Accept ────────────────────────────────────────────────────────────────

    def _accept(self):
        with self._lock:
            suggestion = self._suggestion
            target     = self._fetch_target
        if suggestion and target == self.typed:
            self.typed += suggestion
            with self._lock:
                self._suggestion = ""
            self._schedule_fetch()
            self._render()

    # ── Main input loop ───────────────────────────────────────────────────────

    def readline(self) -> str | None:
        fd  = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        self.typed = ""
        with self._lock:
            self._suggestion   = ""
            self._fetch_target = ""

        try:
            tty.setraw(fd)
            self._render()

            while True:
                ch = sys.stdin.read(1)

                if ch in ("\r", "\n"):
                    sys.stdout.write("\n")
                    sys.stdout.flush()
                    return self.typed

                elif ch == "\x03":              # Ctrl+C
                    sys.stdout.write("\n")
                    sys.stdout.flush()
                    return None

                elif ch == "\x04":              # Ctrl+D
                    sys.stdout.write("\n")
                    sys.stdout.flush()
                    return None

                elif ch == "\x10":              # Ctrl+P — replay last TTS
                    if self._on_replay:
                        threading.Thread(target=self._on_replay, daemon=True).start()

                elif ch in ("\x7f", "\x08"):    # Backspace
                    if self.typed:
                        self.typed = self.typed[:-1]
                    with self._lock:
                        self._suggestion = ""
                    self._schedule_fetch()
                    self._render()

                elif ch == "\t":                # Tab — accept suggestion
                    self._accept()

                elif ch == "\x1b":              # Escape sequence
                    seq = sys.stdin.read(2)
                    if seq == "[C":             # → right arrow — accept
                        self._accept()

                elif ch >= " ":                 # Printable character
                    self.typed += ch
                    with self._lock:
                        self._suggestion = ""
                    self._schedule_fetch()
                    self._render()

        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
            if self._timer:
                self._timer.cancel()


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    print("Japanese Response Tool")
    print("Tab/→: accept suggestion  |  Ctrl+P: replay speech  |  Ctrl+C: quit\n")

    last_japanese: dict[str, str] = {"text": ""}

    def replay():
        speak_japanese(last_japanese["text"])

    widget = GhostInput(on_replay=replay)

    while True:
        text = widget.readline()

        if text is None:
            break

        text = text.strip()
        if not text:
            continue

        print()
        output = stream_translate(text)
        print("\n")

        jp = extract_japanese(output)
        if jp:
            last_japanese["text"] = jp
            _speak_async(jp)


if __name__ == "__main__":
    main()
