"""
Phase 5: YouTube metadata generation using Claude API.

Generates title, description, tags, category, and playlist for each video.
"""

import os
import sys

import config
from utils import (
    log_ok, log_skip, log_err, log_header,
    rate_limit, read_json, write_json, read_text,
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
    "Return ONLY valid JSON, no markdown fences."
)


def _get_client():
    """Lazily create Anthropic client."""
    try:
        import anthropic
    except ImportError:
        print("ERROR: 'anthropic' package not installed. Run: pip install anthropic")
        sys.exit(1)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY environment variable not set.")
        sys.exit(1)

    return anthropic.Anthropic(api_key=api_key)


def generate_metadata(sid: str, sarga_data: dict, script_text: str, client) -> dict:
    """Call Claude to generate YouTube metadata."""
    import json

    rate_limit("claude", config.API_DELAY)

    user_msg = (
        f"Video ID: {sid}\n"
        f"Kanda: {sarga_data.get('kanda', '')}\n"
        f"Sarga: {sarga_data.get('sarga_number', '')}\n"
        f"Chapter Summary: {sarga_data.get('summary', 'N/A')}\n\n"
        f"Narration Script (first 500 words):\n{' '.join(script_text.split()[:500])}\n\n"
        "Generate the YouTube metadata JSON."
    )

    response = client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=1024,
        system=METADATA_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
    )

    raw = response.content[0].text.strip()

    # Try to parse JSON, handle markdown fences if present
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1]
        if raw.endswith("```"):
            raw = raw[:-3]

    meta = json.loads(raw)
    meta["video_id"] = sid
    return meta


def run_metadata():
    """Generate metadata for all available scripts."""
    log_header("PHASE 5: Metadata Generation")
    index = load_index()
    client = _get_client()

    from tqdm import tqdm
    from pathlib import Path

    script_files = sorted(
        Path(config.__file__).parent.joinpath("data", "scripts").glob("*_script.txt")
    )

    if not script_files:
        print("  No scripts found. Run --scripts first.")
        return

    for sf in tqdm(script_files, desc="Generating metadata"):
        sid = sf.stem.replace("_script", "")
        out = meta_path(sid)

        if out.exists():
            log_skip(f"{sid} metadata exists")
            continue

        # Load sarga data
        sp = sarga_path(sid)
        if sp.exists():
            sarga_data = read_json(sp)
        else:
            # For combined/split IDs, try the base sarga
            base_sid = "_".join(sid.split("_")[:2])
            sp = sarga_path(base_sid)
            if sp.exists():
                sarga_data = read_json(sp)
            else:
                sarga_data = {"kanda": "", "sarga_number": 0, "summary": ""}

        script_text = read_text(sf)

        try:
            meta = generate_metadata(sid, sarga_data, script_text, client)
            write_json(out, meta)
            log_ok(f"{sid} → {meta.get('yt_title', '')[:60]}...")
        except Exception as e:
            log_err(f"{sid} → {e}")


if __name__ == "__main__":
    run_metadata()
