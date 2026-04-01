#!/usr/bin/env python3
"""Integration tests for the VOICEVOX TTS pipeline."""

import json
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from urllib.error import URLError

VOICEVOX_URL     = "http://127.0.0.1:50021"
VOICEVOX_SPEAKER = 1
TEST_TEXT        = "こんにちは"

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"

def result(name, ok, detail=""):
    status = PASS if ok else FAIL
    line = f"  [{status}] {name}"
    if detail:
        line += f"\n         {detail}"
    print(line)
    return ok


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_reachable():
    try:
        with urllib.request.urlopen(f"{VOICEVOX_URL}/version", timeout=5) as r:
            version = json.loads(r.read())
        return result("VOICEVOX reachable", True, f"version: {version}")
    except Exception as e:
        return result("VOICEVOX reachable", False, str(e))


def test_speakers():
    try:
        with urllib.request.urlopen(f"{VOICEVOX_URL}/speakers", timeout=5) as r:
            speakers = json.loads(r.read())
        names = [s["name"] for s in speakers[:3]]
        return result("Speakers endpoint", True, f"first 3: {names}")
    except Exception as e:
        return result("Speakers endpoint", False, str(e))


def test_audio_query():
    try:
        params = urllib.parse.urlencode({"text": TEST_TEXT, "speaker": VOICEVOX_SPEAKER})
        req = urllib.request.Request(f"{VOICEVOX_URL}/audio_query?{params}", method="POST")
        with urllib.request.urlopen(req, timeout=10) as r:
            query = json.loads(r.read())
        has_keys = all(k in query for k in ("accent_phrases", "speedScale", "pitchScale"))
        return result("audio_query", has_keys, f"keys present: {list(query.keys())[:5]}")
    except Exception as e:
        return result("audio_query", False, str(e))


def test_synthesis():
    try:
        params = urllib.parse.urlencode({"text": TEST_TEXT, "speaker": VOICEVOX_SPEAKER})
        req = urllib.request.Request(f"{VOICEVOX_URL}/audio_query?{params}", method="POST")
        with urllib.request.urlopen(req, timeout=10) as r:
            query = json.loads(r.read())

        payload = json.dumps(query).encode()
        req2 = urllib.request.Request(
            f"{VOICEVOX_URL}/synthesis?speaker={VOICEVOX_SPEAKER}",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req2, timeout=30) as r:
            wav = r.read()

        is_wav = wav[:4] == b"RIFF"
        return result("synthesis → WAV", is_wav, f"{len(wav)} bytes, header: {wav[:4]}")
    except Exception as e:
        return result("synthesis → WAV", False, str(e))


def test_paplay_stdin():
    """Check paplay accepts WAV from stdin (no filename arg)."""
    try:
        proc = subprocess.run(
            ["paplay", "--help"],
            capture_output=True, text=True, timeout=5
        )
        # paplay reads stdin when no file is given
        available = proc.returncode == 0 or "Usage" in proc.stdout + proc.stderr
        return result("paplay available", available, proc.stderr[:80] if proc.stderr else "ok")
    except FileNotFoundError:
        return result("paplay available", False, "paplay not found — install libpulse")
    except Exception as e:
        return result("paplay available", False, str(e))


def test_full_pipeline():
    """Full end-to-end: Japanese text → VOICEVOX → WAV → paplay (1 second)."""
    try:
        # 1. audio_query
        params = urllib.parse.urlencode({"text": TEST_TEXT, "speaker": VOICEVOX_SPEAKER})
        req = urllib.request.Request(f"{VOICEVOX_URL}/audio_query?{params}", method="POST")
        with urllib.request.urlopen(req, timeout=10) as r:
            query = json.loads(r.read())

        # 2. synthesis
        payload = json.dumps(query).encode()
        req2 = urllib.request.Request(
            f"{VOICEVOX_URL}/synthesis?speaker={VOICEVOX_SPEAKER}",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req2, timeout=30) as r:
            wav = r.read()

        # 3. play — paplay reads from stdin when no filename is given
        proc = subprocess.Popen(
            ["paplay", "--stream-name=ja-respond-test"],
            stdin=subprocess.PIPE,
        )
        proc.stdin.write(wav)
        proc.stdin.close()
        proc.wait()

        ok = proc.returncode == 0
        return result("full pipeline (should have heard audio)", ok,
                      f"paplay exit code: {proc.returncode}")
    except Exception as e:
        return result("full pipeline", False, str(e))


# ── Runner ────────────────────────────────────────────────────────────────────

def main():
    print(f"\nVOICEVOX integration tests  (text: {TEST_TEXT!r}, speaker: {VOICEVOX_SPEAKER})\n")

    tests = [
        test_reachable,
        test_speakers,
        test_audio_query,
        test_synthesis,
        test_paplay_stdin,
        test_full_pipeline,
    ]

    results = [t() for t in tests]
    passed  = sum(results)
    total   = len(results)

    print(f"\n{passed}/{total} passed")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
