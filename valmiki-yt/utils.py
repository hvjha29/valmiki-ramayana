"""Shared helpers: logging, file I/O, rate limiting, index management."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Union

# ── Paths ──────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
SARGAS_DIR = DATA / "sargas"
SCRIPTS_DIR = DATA / "scripts"
AUDIO_DIR = DATA / "audio"
VIDEOS_DIR = DATA / "videos"
META_DIR = DATA / "metadata"
ASSETS_DIR = ROOT / "assets"
INDEX_PATH = DATA / "index.json"

for d in (SARGAS_DIR, SCRIPTS_DIR, AUDIO_DIR, VIDEOS_DIR, META_DIR, ASSETS_DIR):
    d.mkdir(parents=True, exist_ok=True)


# ── Logging helpers ────────────────────────────────────────────────────────
def log_ok(msg: str):
    print(f"  ✓ {msg}")


def log_skip(msg: str):
    print(f"  ⚠ {msg}")


def log_err(msg: str):
    print(f"  ✗ {msg}")


def log_header(msg: str):
    print(f"\n{'─'*60}\n  {msg}\n{'─'*60}")


# ── Timestamps ─────────────────────────────────────────────────────────────
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── JSON I/O (UTF-8) ──────────────────────────────────────────────────────
def read_json(path: Path) -> Union[dict, list]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def write_text(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def read_text(path: Path) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


# ── Rate limiting ──────────────────────────────────────────────────────────
_last_call = {}  # type: dict


def rate_limit(key: str, delay: float):
    """Sleep if needed to maintain `delay` seconds between calls keyed by `key`."""
    now = time.time()
    last = _last_call.get(key, 0)
    wait = delay - (now - last)
    if wait > 0:
        time.sleep(wait)
    _last_call[key] = time.time()


# ── Index management ──────────────────────────────────────────────────────
def load_index() -> list[dict]:
    if INDEX_PATH.exists():
        return read_json(INDEX_PATH)
    return []


def save_index(index: list[dict]):
    write_json(INDEX_PATH, index)


def index_lookup(index: list[dict]) -> dict[str, dict]:
    """Return {id: entry} dict for fast lookup."""
    return {e["id"]: e for e in index}


def upsert_index(index: list[dict], entry: dict) -> list[dict]:
    """Insert or update an entry in the index list (by id)."""
    for i, e in enumerate(index):
        if e["id"] == entry["id"]:
            index[i] = entry
            return index
    index.append(entry)
    return index


# ── Sarga file helpers ────────────────────────────────────────────────────
def sarga_path(sid: str) -> Path:
    return SARGAS_DIR / f"{sid}.json"


def script_path(sid: str) -> Path:
    return SCRIPTS_DIR / f"{sid}_script.txt"


def audio_path(sid: str) -> Path:
    return AUDIO_DIR / f"{sid}.mp3"


def video_path(sid: str) -> Path:
    return VIDEOS_DIR / f"{sid}.mp4"


def meta_path(sid: str) -> Path:
    return META_DIR / f"{sid}_meta.json"


def sarga_exists(sid: str) -> bool:
    return sarga_path(sid).exists()


# ── Status table printer ─────────────────────────────────────────────────
def print_status_table(index: list[dict]):
    """Print a summary table grouped by kanda."""
    from config import KANDAS

    header = f"{'Kanda':<20} {'Total':>6} {'OK':>6} {'Error':>6} {'Skip':>6}"
    print(f"\n{header}")
    print("─" * len(header))

    grand = {"total": 0, "ok": 0, "error": 0, "skipped": 0}
    for kanda_key, info in KANDAS.items():
        entries = [e for e in index if e.get("kanda_key") == kanda_key]
        ok = sum(1 for e in entries if e.get("status") == "ok")
        err = sum(1 for e in entries if e.get("status") == "error")
        skip = sum(1 for e in entries if e.get("status") == "skipped")
        total = len(entries)
        print(f"{info['name']:<20} {total:>6} {ok:>6} {err:>6} {skip:>6}")
        grand["total"] += total
        grand["ok"] += ok
        grand["error"] += err
        grand["skipped"] += skip

    print("─" * len(header))
    print(
        f"{'TOTAL':<20} {grand['total']:>6} {grand['ok']:>6} "
        f"{grand['error']:>6} {grand['skipped']:>6}"
    )


def print_pipeline_status():
    """Full pipeline status: scraped / scripted / audio / video / metadata."""
    from config import KANDAS

    index = load_index()
    lu = index_lookup(index)

    header = (
        f"{'Kanda':<20} {'Scraped':>8} {'Script':>8} "
        f"{'Audio':>8} {'Video':>8} {'Meta':>8}"
    )
    print(f"\n{header}")
    print("─" * len(header))

    for kanda_key, info in KANDAS.items():
        entries = [e for e in index if e.get("kanda_key") == kanda_key and e.get("status") == "ok"]
        scraped = len(entries)
        scripts = sum(1 for e in entries if script_path(e["id"]).exists())
        audios = sum(1 for e in entries if audio_path(e["id"]).exists())
        videos = sum(1 for e in entries if video_path(e["id"]).exists())
        metas = sum(1 for e in entries if meta_path(e["id"]).exists())
        print(
            f"{info['name']:<20} {scraped:>8} {scripts:>8} "
            f"{audios:>8} {videos:>8} {metas:>8}"
        )

    print()
