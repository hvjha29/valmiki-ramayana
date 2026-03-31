#!/usr/bin/env python3
"""
valmiki-yt — Pipeline CLI entry point.

Usage:
  python run.py --scrape [--kanda baala] [--dry-run]
  python run.py --scripts
  python run.py --audio
  python run.py --video
  python run.py --metadata
  python run.py --all [--kanda baala]
  python run.py --status
  python run.py --resume
"""

import argparse
import sys
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parent))


def main():
    parser = argparse.ArgumentParser(
        description="Valmiki Ramayana → YouTube narration pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument("--scrape", action="store_true", help="Phase 1: Scrape prose translations")
    parser.add_argument("--scripts", action="store_true", help="Phase 2: Generate narration scripts (Claude)")
    parser.add_argument("--audio", action="store_true", help="Phase 3: Text-to-speech (gTTS)")
    parser.add_argument("--video", action="store_true", help="Phase 4: Video assembly (moviepy)")
    parser.add_argument("--metadata", action="store_true", help="Phase 5: YouTube metadata (Claude)")
    parser.add_argument("--all", action="store_true", help="Run all phases in sequence")
    parser.add_argument("--status", action="store_true", help="Print pipeline status table")
    parser.add_argument("--resume", action="store_true", help="Re-run only errored items")
    parser.add_argument("--kanda", type=str, default=None,
                        help="Filter to a single kanda (e.g. baala, ayodhya, kish)")
    parser.add_argument("--dry-run", action="store_true",
                        help="(Scrape only) Print URLs without fetching")

    args = parser.parse_args()

    # Default: show help
    if not any([args.scrape, args.scripts, args.audio, args.video,
                args.metadata, args.all, args.status, args.resume]):
        parser.print_help()
        return

    # Validate kanda filter
    if args.kanda:
        from config import KANDAS
        if args.kanda not in KANDAS:
            print(f"ERROR: Unknown kanda '{args.kanda}'. Valid: {', '.join(KANDAS.keys())}")
            sys.exit(1)

    # ── Status ─────────────────────────────────────────────────────────
    if args.status:
        from utils import print_pipeline_status
        print_pipeline_status()
        return

    # ── Phase 1: Scrape ────────────────────────────────────────────────
    if args.scrape or args.all:
        from scraper import run_scrape, dry_run
        if args.dry_run:
            dry_run(args.kanda)
            if not args.all:
                return
        else:
            run_scrape(kanda_filter=args.kanda, resume=args.resume)

    # ── Phase 2: Scripts ───────────────────────────────────────────────
    if args.scripts or args.all:
        from script_gen import run_scripts
        run_scripts()

    # ── Phase 3: Audio ─────────────────────────────────────────────────
    if args.audio or args.all:
        from tts import run_tts
        run_tts()

    # ── Phase 4: Video ─────────────────────────────────────────────────
    if args.video or args.all:
        from video_builder import run_video
        run_video()

    # ── Phase 5: Metadata ──────────────────────────────────────────────
    if args.metadata or args.all:
        from metadata_gen import run_metadata
        run_metadata()

    # ── Resume (re-run errored items) ──────────────────────────────────
    if args.resume and not args.scrape and not args.all:
        from scraper import run_scrape
        run_scrape(kanda_filter=args.kanda, resume=True)


if __name__ == "__main__":
    main()
