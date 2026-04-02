"""
Phase 2: Generate narration scripts using Hugging Face Inference API.

Handles combining short sargas and splitting long ones to target 3-6 min videos.
Includes quality check: verifies expected character names appear in output to
catch hallucinations from smaller models.
"""
from __future__ import annotations

import re
import sys
from collections import defaultdict
from typing import Optional

import config
from hf_client import HFClient
from utils import (
    log_ok, log_skip, log_err, log_header,
    read_json, write_text, read_text,
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
    "only, no stage directions, no headers. (6) Aim for 500-900 words."
)


# ── Quality check ─────────────────────────────────────────────────────────────

def check_script_quality(script: str, kanda_key: str) -> tuple:
    """
    Verify that at least 3 expected character names from this kanda appear
    in the generated script.

    Returns:
        (passed: bool, match_count: int, matched_names: list[str])
    """
    expected = config.KANDA_EXPECTED_NAMES.get(kanda_key, [])
    if not expected:
        return True, 0, []  # no list defined → skip check

    script_lower = script.lower()
    matched = []
    for name in expected:
        if re.search(r'\b' + re.escape(name.lower()) + r'\b', script_lower):
            matched.append(name)

    passed = len(matched) >= 3
    return passed, len(matched), matched


# ── Script generation ─────────────────────────────────────────────────────────

def generate_script(text: str, title: str, client: HFClient) -> Optional[str]:
    """Call HF model to generate a narration script from prose translation."""
    user_msg = (
        f"Chapter: {title}\n\n"
        f"Prose translation:\n{text}\n\n"
        "Please rewrite this as a narration script."
    )
    return client.generate(SYSTEM_PROMPT, user_msg)


def _plan_scripts(index: list, kanda_filter: Optional[str] = None) -> list:
    """
    Plan which sargas to combine/split based on word count.
    Returns a list of script plan dicts.
    """
    plans = []
    ok_entries = [e for e in index if e.get("status") == "ok"]

    by_kanda = defaultdict(list)
    for e in ok_entries:
        by_kanda[e["kanda_key"]].append(e)

    for kanda_key in config.KANDAS:
        if kanda_filter and kanda_key != kanda_filter:
            continue

        entries = sorted(by_kanda.get(kanda_key, []), key=lambda e: e["sarga_number"])
        i = 0
        while i < len(entries):
            e = entries[i]
            wc = e.get("word_count", 0)

            if wc < config.SCRIPT_MIN_WORDS and i + 1 < len(entries):
                next_e = entries[i + 1]
                combined_id = f"{e['id']}_{next_e['sarga_number']:03d}"
                plans.append({
                    "id": combined_id,
                    "sargas": [e["id"], next_e["id"]],
                    "type": "combined",
                    "kanda_key": kanda_key,
                    "title": f"{e['kanda']} - Sargas {e['sarga_number']}-{next_e['sarga_number']}",
                })
                i += 2
            elif wc > config.SCRIPT_MAX_WORDS:
                plans.append({
                    "id": f"{e['id']}_p1",
                    "sargas": [e["id"]],
                    "type": "split",
                    "part": 1,
                    "kanda_key": kanda_key,
                    "title": f"{e['kanda']} - Sarga {e['sarga_number']} (Part 1)",
                })
                plans.append({
                    "id": f"{e['id']}_p2",
                    "sargas": [e["id"]],
                    "type": "split",
                    "part": 2,
                    "kanda_key": kanda_key,
                    "title": f"{e['kanda']} - Sarga {e['sarga_number']} (Part 2)",
                })
                i += 1
            else:
                plans.append({
                    "id": e["id"],
                    "sargas": [e["id"]],
                    "type": "single",
                    "kanda_key": kanda_key,
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


def run_scripts(
    kanda_filter: Optional[str] = None,
    pinned_model: Optional[str] = None,
    sarga_limit: Optional[int] = None,
    print_scripts: bool = False,
):
    """
    Generate narration scripts for all scraped sargas.

    Args:
        kanda_filter: Only process this kanda (e.g. "baala").
        pinned_model: Pin to a specific model (skip fallback chain).
        sarga_limit:  Max number of sargas to process (for testing).
        print_scripts: If True, print each generated script to stdout.
    """
    log_header("PHASE 2: Script Generation (Hugging Face)")
    client = HFClient(pinned_model=pinned_model)

    index = load_index()
    plans = _plan_scripts(index, kanda_filter=kanda_filter)

    if sarga_limit:
        plans = plans[:sarga_limit]

    if not plans:
        print("  No sargas to process. Run --scrape first.")
        return

    print(f"  Processing {len(plans)} script(s)...\n")

    from tqdm import tqdm

    stats = {"ok": 0, "low_confidence": 0, "error": 0, "skipped": 0}

    for plan in tqdm(plans, desc="Generating scripts"):
        out_path = script_path(plan["id"])

        if out_path.exists():
            log_skip(f"{plan['id']} script exists")
            stats["skipped"] += 1
            continue

        # Load and concatenate texts
        texts = [_load_sarga_text(sid) for sid in plan["sargas"]]
        texts = [t for t in texts if t]

        if not texts:
            log_err(f"{plan['id']} → no text available")
            stats["error"] += 1
            continue

        full_text = "\n\n".join(texts)

        # For splits, take first or second half
        if plan["type"] == "split":
            sentences = full_text.split(". ")
            mid = len(sentences) // 2
            if plan.get("part") == 1:
                full_text = ". ".join(sentences[:mid]) + "."
            else:
                full_text = ". ".join(sentences[mid:])

        # ── Truncate to stay within model context ────────────────────
        if len(full_text) > config.HF_MAX_INPUT_CHARS:
            log_skip(
                f"{plan['id']} input {len(full_text)} chars → "
                f"truncated to {config.HF_MAX_INPUT_CHARS}"
            )
            full_text = (
                full_text[:config.HF_MAX_INPUT_CHARS]
                + "\n\n[Translation continues — narrate what is provided above.]"
            )

        try:
            script = generate_script(full_text, plan["title"], client)

            if not script:
                log_err(f"{plan['id']} → model returned no output")
                stats["error"] += 1
                continue

            # ── Quality check ────────────────────────────────────────
            kanda_key = plan.get("kanda_key", plan["id"].split("_")[0])
            passed, n_matches, matched = check_script_quality(script, kanda_key)

            word_count = len(script.split())

            if passed:
                write_text(out_path, script)
                log_ok(f"{plan['id']} ({word_count} words, {n_matches} names: {matched})")
                stats["ok"] += 1
            else:
                # Save anyway but flag it
                write_text(out_path, script)
                log_err(
                    f"⚠ LOW CONFIDENCE: {plan['id']} — only {n_matches}/3 "
                    f"expected names found ({matched}). "
                    f"Saved but flagged for review."
                )
                stats["low_confidence"] += 1

                # Update index with low_confidence flag
                for entry in index:
                    if entry["id"] in plan["sargas"]:
                        entry["script_status"] = "low_confidence"
                        entry["script_names_matched"] = n_matches
                save_index(index)

            # ── Print to console if requested ────────────────────────
            if print_scripts:
                quality = "✓ PASSED" if passed else f"⚠ LOW CONFIDENCE ({n_matches}/3)"
                print(f"\n{'='*70}")
                print(f"  SCRIPT: {plan['id']} | {word_count} words | {quality}")
                print(f"  Names: {matched}")
                print(f"{'='*70}\n")
                print(script)
                print(f"\n{'='*70}\n")

        except Exception as e:
            log_err(f"{plan['id']} → {e}")
            stats["error"] += 1

    # ── Summary ──────────────────────────────────────────────────────────
    print(f"\n{'─'*60}")
    print(
        f"  Scripts: ✓ {stats['ok']} ok | "
        f"⚠ {stats['low_confidence']} low-confidence | "
        f"⚠ {stats['skipped']} skipped | "
        f"✗ {stats['error']} errors"
    )
    print(f"{'─'*60}\n")


if __name__ == "__main__":
    run_scripts()
