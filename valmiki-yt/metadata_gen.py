"""
Phase 5: YouTube metadata generation using Hugging Face Inference API.

Generates title, description, tags, category, and playlist for each video.
Includes deterministic fallback templates when model fails to return valid JSON.
"""
from __future__ import annotations

import json
import sys
from typing import Optional

import config
from hf_client import HFClient
from utils import (
    log_ok, log_skip, log_err, log_header,
    read_json, write_json, read_text,
    sarga_path, script_path, meta_path,
    load_index,
)


METADATA_SYSTEM_PROMPT = (
    "You are a YouTube metadata expert for an educational Hindu epic narration "
    "channel. Given a chapter summary and narration script from Valmiki Ramayana, "
    "generate YouTube metadata in JSON format with these exact keys:\n"
    '  "yt_title": a compelling title ≤100 chars, format: '
    '"Valmiki Ramayana | {Kanda} | Sarga {N} | {hook}"\n'
    '  "yt_description": 3-4 sentences summarizing the sarga, followed by: '
    '"This is an unabridged narration from Valmiki Ramayana, translated by '
    'Desiraju Hanumanta Rao." Add a standard CTA placeholder.\n'
    '  "yt_tags": array of 10-15 relevant tags including "Valmiki Ramayana", '
    "the kanda name, sarga number, and topical tags\n"
    '  "yt_category": "Education"\n'
    '  "playlist": the kanda name\n'
    "Return ONLY valid JSON, no markdown fences, no explanation."
)


def _parse_json_response(text: str) -> Optional[dict]:
    """Try to extract valid JSON from the model's response."""
    # Strip markdown fences
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]

    # Direct parse
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass

    # Find JSON object in the text
    start = text.find("{")
    end = text.rfind("}") + 1
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end])
        except json.JSONDecodeError:
            pass

    return None


def _fallback_metadata(sarga_data: dict) -> dict:
    """Deterministic metadata template when model fails to return valid JSON."""
    kanda = sarga_data.get("kanda", "Unknown Kanda")
    sarga = sarga_data.get("sarga_number", 0)
    summary = sarga_data.get("summary", "")

    subtitle = ""
    if summary:
        first_sentence = summary.split(".")[0].strip()
        if len(first_sentence) > 10:
            subtitle = f" | {first_sentence[:60]}"

    return {
        "yt_title": f"Valmiki Ramayana | {kanda} | Sarga {sarga}{subtitle}",
        "yt_description": (
            f"{kanda}, Sarga {sarga}. {summary[:200] if summary else ''} "
            f"This is from the unabridged Valmiki Ramayana, translated by "
            f"Desiraju Hanumanta Rao. Subscribe for daily episodes."
        ),
        "yt_tags": [
            "Valmiki Ramayana", kanda, f"Sarga {sarga}",
            "Hindu epic", "Rama", "Sanskrit epic English",
            "Ramayana narration", "Indian mythology",
            "Vedic literature", "Ramayana audiobook",
            "Hindu scripture", "Ancient Indian epic",
        ],
        "yt_category": "Education",
        "playlist": kanda,
        "_generated_by": "fallback_template",
    }


def generate_metadata(sid: str, sarga_data: dict, script_text: str, client: HFClient) -> dict:
    """Generate YouTube metadata for one video."""
    user_msg = (
        f"Video ID: {sid}\n"
        f"Kanda: {sarga_data.get('kanda', '')}\n"
        f"Sarga: {sarga_data.get('sarga_number', '')}\n"
        f"Chapter Summary: {sarga_data.get('summary', 'N/A')}\n\n"
        f"Narration Script (first 500 words):\n{' '.join(script_text.split()[:500])}\n\n"
        "Generate the YouTube metadata JSON."
    )

    result = client.generate(METADATA_SYSTEM_PROMPT, user_msg)

    if result:
        meta = _parse_json_response(result)
        if meta:
            meta["video_id"] = sid
            return meta

    # Fallback to deterministic template
    log_err(f"{sid} → model response wasn't valid JSON, using fallback template")
    meta = _fallback_metadata(sarga_data)
    meta["video_id"] = sid
    return meta


def run_metadata(
    kanda_filter: Optional[str] = None,
    pinned_model: Optional[str] = None,
):
    """Generate metadata for all available scripts."""
    log_header("PHASE 5: Metadata Generation (Hugging Face)")
    client = HFClient(pinned_model=pinned_model)

    from tqdm import tqdm
    from pathlib import Path

    script_files = sorted(
        Path(config.__file__).parent.joinpath("data", "scripts").glob("*_script.txt")
    )

    if not script_files:
        print("  No scripts found. Run --scripts first.")
        return

    stats = {"ok": 0, "fallback": 0, "skipped": 0, "error": 0}

    for sf in tqdm(script_files, desc="Generating metadata"):
        sid = sf.stem.replace("_script", "")

        # Apply kanda filter
        if kanda_filter and not sid.startswith(kanda_filter):
            continue

        out = meta_path(sid)
        if out.exists():
            log_skip(f"{sid} metadata exists")
            stats["skipped"] += 1
            continue

        # Load sarga data
        sp = sarga_path(sid)
        if sp.exists():
            sarga_data = read_json(sp)
        else:
            base_sid = "_".join(sid.split("_")[:2])
            sp = sarga_path(base_sid)
            sarga_data = read_json(sp) if sp.exists() else {"kanda": "", "sarga_number": 0, "summary": ""}

        script_text = read_text(sf)

        try:
            meta = generate_metadata(sid, sarga_data, script_text, client)
            write_json(out, meta)

            if meta.get("_generated_by") == "fallback_template":
                log_ok(f"{sid} → fallback template")
                stats["fallback"] += 1
            else:
                log_ok(f"{sid} → {meta.get('yt_title', '')[:60]}...")
                stats["ok"] += 1
        except Exception as e:
            log_err(f"{sid} → {e}")
            stats["error"] += 1

    print(f"\n{'─'*60}")
    print(
        f"  Metadata: ✓ {stats['ok']} ok | "
        f"📋 {stats['fallback']} fallback | "
        f"⚠ {stats['skipped']} skipped | "
        f"✗ {stats['error']} errors"
    )
    print(f"{'─'*60}\n")


if __name__ == "__main__":
    run_metadata()
