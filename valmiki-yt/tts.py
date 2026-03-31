"""
Phase 3: Text-to-Speech using gTTS.

Note: gTTS is a placeholder for channel-quality audio.
Recommended upgrade: ElevenLabs (voice: "Clyde" or "Adam" for gravitas).
"""

import sys

import config
from utils import (
    log_ok, log_skip, log_err, log_header,
    script_path, audio_path, read_text,
    load_index,
    AUDIO_DIR,
)


def generate_audio(text: str, output_path):
    """Generate MP3 from text using gTTS."""
    try:
        from gtts import gTTS
    except ImportError:
        print("ERROR: 'gTTS' package not installed. Run: pip install gTTS")
        sys.exit(1)

    tts = gTTS(text=text, lang=config.TTS_LANG, slow=config.TTS_SLOW)
    tts.save(str(output_path))


def run_tts():
    """Generate audio for all available scripts."""
    log_header("PHASE 3: Text-to-Speech")
    index = load_index()

    from tqdm import tqdm
    from pathlib import Path

    # Collect all script files
    script_files = sorted(Path(config.__file__).parent.joinpath("data", "scripts").glob("*_script.txt"))

    if not script_files:
        print("  No scripts found. Run --scripts first.")
        return

    for sf in tqdm(script_files, desc="Generating audio"):
        # Derive ID from filename: baala_001_script.txt → baala_001
        sid = sf.stem.replace("_script", "")
        out = audio_path(sid)

        if out.exists():
            log_skip(f"{sid} audio exists")
            continue

        text = read_text(sf)
        if not text.strip():
            log_err(f"{sid} → empty script")
            continue

        try:
            generate_audio(text, out)
            log_ok(f"{sid} → {out.name}")
        except Exception as e:
            log_err(f"{sid} → {e}")


if __name__ == "__main__":
    run_tts()
