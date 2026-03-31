"""
Phase 2: Generate narration scripts using Claude API.

Handles combining short sargas and splitting long ones to target 3-6 min videos.
"""

import os
import sys

import config
from utils import (
    log_ok, log_skip, log_err, log_header,
    rate_limit, read_json, write_text, read_text,
    sarga_path, script_path, sarga_exists,
    load_index, save_index, upsert_index,
    SCRIPTS_DIR,
)

SYSTEM_PROMPT = (
    "You are a scholar-narrator presenting Valmiki Ramayana to a general "
    "English-speaking audience. You have deep reverence for the text. Given the "
    "prose translation of a sarga (chapter), rewrite it as a flowing, engaging "
    "narration script for a 3-6 minute YouTube video. Rules: (1) Stay faithful "
    "to Valmiki — do not add modern interpretations or dramatize beyond what "
    "the text says. (2) Begin with one sentence situating the listener in the "
    "story so far. (3) Use clear, dignified English — not archaic, not casual. "
    "(4) End with the chapter's significance in one sentence. (5) Plain text "
    "only, no stage directions, no headers."
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


def generate_script(text: str, title: str, client) -> str:
    """Call Claude to generate a narration script."""
    rate_limit("claude", config.API_DELAY)

    user_msg = (
        f"Chapter: {title}\n\n"
        f"Prose translation:\n{text}\n\n"
        "Please rewrite this as a narration script."
    )

    response = client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
    )

    return response.content[0].text.strip()


def _plan_scripts(index: list[dict]) -> list[dict]:
    """
    Plan which sargas to combine/split based on word count.

    Returns a list of script plans:
      {"id": "baala_001", "sargas": ["baala_001"], "type": "single"}
      {"id": "baala_002_003", "sargas": ["baala_002", "baala_003"], "type": "combined"}
      {"id": "baala_010_p1", "sargas": ["baala_010"], "type": "split", "part": 1}
    """
    plans = []
    ok_entries = [e for e in index if e.get("status") == "ok"]

    # Group by kanda
    from collections import defaultdict
    by_kanda = defaultdict(list)
    for e in ok_entries:
        by_kanda[e["kanda_key"]].append(e)

    for kanda_key in config.KANDAS:
        entries = sorted(by_kanda.get(kanda_key, []), key=lambda e: e["sarga_number"])
        i = 0
        while i < len(entries):
            e = entries[i]
            wc = e.get("word_count", 0)

            if wc < config.SCRIPT_MIN_WORDS and i + 1 < len(entries):
                # Combine with next sarga
                next_e = entries[i + 1]
                combined_id = f"{e['id']}_{next_e['sarga_number']:03d}"
                plans.append({
                    "id": combined_id,
                    "sargas": [e["id"], next_e["id"]],
                    "type": "combined",
                    "title": f"{e['kanda']} - Sargas {e['sarga_number']}-{next_e['sarga_number']}",
                })
                i += 2
            elif wc > config.SCRIPT_MAX_WORDS:
                # Split into two
                plans.append({
                    "id": f"{e['id']}_p1",
                    "sargas": [e["id"]],
                    "type": "split",
                    "part": 1,
                    "title": f"{e['kanda']} - Sarga {e['sarga_number']} (Part 1)",
                })
                plans.append({
                    "id": f"{e['id']}_p2",
                    "sargas": [e["id"]],
                    "type": "split",
                    "part": 2,
                    "title": f"{e['kanda']} - Sarga {e['sarga_number']} (Part 2)",
                })
                i += 1
            else:
                plans.append({
                    "id": e["id"],
                    "sargas": [e["id"]],
                    "type": "single",
                    "title": f"{e['kanda']} - Sarga {e['sarga_number']}",
                })
                i += 1

    return plans


def _load_sarga_text(sid: str) -> str:
    """Load translation text from a sarga JSON file."""
    path = sarga_path(sid)
    if not path.exists():
        return ""
    data = read_json(path)
    return data.get("translation_text", "")


def run_scripts():
    """Generate narration scripts for all scraped sargas."""
    log_header("PHASE 2: Script Generation")
    index = load_index()
    plans = _plan_scripts(index)
    client = _get_client()

    from tqdm import tqdm

    for plan in tqdm(plans, desc="Generating scripts"):
        out_path = script_path(plan["id"])
        if out_path.exists():
            log_skip(f"{plan['id']} script exists")
            continue

        # Load and concatenate texts
        texts = []
        for sid in plan["sargas"]:
            t = _load_sarga_text(sid)
            if t:
                texts.append(t)

        if not texts:
            log_err(f"{plan['id']} → no text available")
            continue

        full_text = "\n\n".join(texts)

        # For splits, divide text roughly in half
        if plan["type"] == "split":
            sentences = full_text.split(". ")
            mid = len(sentences) // 2
            if plan.get("part") == 1:
                full_text = ". ".join(sentences[:mid]) + "."
            else:
                full_text = ". ".join(sentences[mid:])

        try:
            script = generate_script(full_text, plan["title"], client)
            write_text(out_path, script)
            log_ok(f"{plan['id']} ({len(script.split())} words)")
        except Exception as e:
            log_err(f"{plan['id']} → {e}")


if __name__ == "__main__":
    run_scripts()
