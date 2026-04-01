#!/usr/bin/env python3
# Background clipboard watcher: detects copied Japanese text, translates to English.
#
# Usage:
#   python3 tools/ja-clip.py
#
# Leave running in a terminal or add to your autostart.
# Requires: wl-clipboard (wl-paste), libnotify (notify-send), llama-server on port 8081

import json
import subprocess
import sys
import time
import urllib.request
from urllib.error import URLError

LLAMA_URL = "http://127.0.0.1:8081/v1/chat/completions"

SYSTEM_PROMPT = (
    "You are a Japanese translation assistant. "
    "Respond only in the exact format requested. No extra commentary."
)

USER_PROMPT = """Translate this Japanese text to English:
"{text}"

Format your response exactly like this:
English: <natural translation>
Literal: <word-for-word back-translation>

Breakdown:
- <word or particle>: <meaning and grammatical role>"""

JAPANESE_RANGES = [
    (0x3040, 0x309F),  # Hiragana
    (0x30A0, 0x30FF),  # Katakana
    (0x4E00, 0x9FFF),  # CJK Unified Ideographs (Kanji)
    (0x3400, 0x4DBF),  # CJK Extension A
]


def is_japanese(text: str) -> bool:
    return any(
        any(lo <= ord(ch) <= hi for lo, hi in JAPANESE_RANGES)
        for ch in text
    )


def get_clipboard() -> str:
    result = subprocess.run(
        ["wl-paste", "--no-newline"],
        capture_output=True,
        text=True,
    )
    return result.stdout if result.returncode == 0 else ""


def notify(summary: str, body: str = ""):
    subprocess.run(["notify-send", "-t", "15000", summary, body])


def stream_translate(text: str) -> str:
    payload = json.dumps({
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": USER_PROMPT.format(text=text)},
        ],
        "stream": True,
        "temperature": 0.2,
        "cache_prompt": True,
    }).encode()

    req = urllib.request.Request(
        LLAMA_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
    )

    tokens = []
    try:
        with urllib.request.urlopen(req) as resp:
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
        print("Error: llama-server not running on port 8081.", file=sys.stderr)
        return ""

    return "".join(tokens)


def main():
    print("Clipboard watcher running — copy Japanese text to translate (Ctrl+C to quit)\n", flush=True)
    last = ""

    while True:
        clip = get_clipboard()

        if clip and clip != last and is_japanese(clip):
            print(f"--- Detected Japanese ---\n{clip}\n", flush=True)
            result = stream_translate(clip)
            print("\n", flush=True)

            english_line = next(
                (l for l in result.splitlines() if l.startswith("English:")),
                "Translation ready — see terminal for breakdown",
            )
            notify("Japanese → English", english_line)

        last = clip
        time.sleep(0.5)


if __name__ == "__main__":
    main()
