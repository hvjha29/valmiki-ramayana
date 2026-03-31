"""
Phase 4: Video assembly using moviepy.

Layout (portrait 1080×1920 for YouTube Shorts / vertical feed):
  - Background: static image from assets/bg_{kanda_key}.jpg
    Fallback to assets/bg_default.jpg if kanda-specific image missing
  - Top 15%: Kanda name + Sarga number in gold/saffron text
  - Middle 70%: background image
  - Bottom 15%: subtitle text (white, shadowed)
  - Audio: generated MP3, video duration = audio duration

Subtitles: script chunked into ~8-word segments, timed evenly.
Falls back to no subtitles + log warning if font issues arise.
"""

import sys
import textwrap
from pathlib import Path

# ── Pillow compat: moviepy 1.0.3 uses Image.ANTIALIAS, removed in Pillow 10+ ─
from PIL import Image
if not hasattr(Image, "ANTIALIAS"):
    Image.ANTIALIAS = Image.LANCZOS

# ── ImageMagick config ────────────────────────────────────────────────────────
import os
if not os.environ.get("IMAGEMAGICK_BINARY"):
    for _p in ("/opt/homebrew/bin/convert", "/usr/local/bin/convert", "/usr/bin/convert"):
        if Path(_p).exists():
            os.environ["IMAGEMAGICK_BINARY"] = _p
            break

import config
from utils import (
    log_ok, log_skip, log_err, log_header,
    read_json, read_text,
    sarga_path, script_path, audio_path, video_path,
    load_index,
    ASSETS_DIR, VIDEOS_DIR,
)


def _get_bg_image(kanda_key: str) -> str:
    """Return path to background image, with fallback."""
    specific = ASSETS_DIR / f"bg_{kanda_key}.jpg"
    default = ASSETS_DIR / "bg_default.jpg"
    if specific.exists():
        return str(specific)
    if default.exists():
        return str(default)
    return ""


# ── Font resolution ───────────────────────────────────────────────────────────

def _find_font(bold: bool = False) -> str:
    """Find a usable font path on macOS / Linux."""
    candidates_bold = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/HelveticaNeue.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    candidates_regular = [
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/HelveticaNeue.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for fp in (candidates_bold if bold else candidates_regular):
        if Path(fp).exists():
            return fp
    return "Helvetica"  # fallback name


FONT_BOLD = _find_font(bold=True)
FONT_REGULAR = _find_font(bold=False)


def _chunk_text(text: str, words_per_chunk: int = 8) -> list[str]:
    """Split text into chunks of approximately `words_per_chunk` words."""
    words = text.split()
    chunks = []
    for i in range(0, len(words), words_per_chunk):
        chunks.append(" ".join(words[i:i + words_per_chunk]))
    return chunks


def build_video(sid: str, kanda_key: str, sarga_num: int, kanda_name: str):
    """Assemble a single video."""
    try:
        from moviepy.editor import (
            AudioFileClip, ImageClip, CompositeVideoClip, TextClip, ColorClip
        )
    except ImportError:
        print("ERROR: 'moviepy' not installed. Run: pip install moviepy==1.0.3")
        sys.exit(1)

    audio_file = audio_path(sid)
    script_file = script_path(sid)
    output_file = video_path(sid)

    if not audio_file.exists():
        log_err(f"{sid} → no audio file")
        return
    if not script_file.exists():
        log_err(f"{sid} → no script file")
        return

    audio_clip = AudioFileClip(str(audio_file))
    duration = audio_clip.duration

    W, H = config.VIDEO_WIDTH, config.VIDEO_HEIGHT

    # Background
    bg_path = _get_bg_image(kanda_key)
    if bg_path:
        bg = ImageClip(bg_path).set_duration(duration).resize((W, H))
    else:
        bg = ColorClip(size=(W, H), color=(20, 10, 5)).set_duration(duration)

    layers = [bg]

    # Title overlay (top 15%)
    title_text = f"{kanda_name}\nSarga {sarga_num}"
    try:
        title_clip = (
            TextClip(
                title_text,
                fontsize=56,
                color="#FFD700",  # gold
                font=FONT_BOLD,
                size=(W - 80, int(H * 0.15)),
                method="caption",
            )
            .set_position(("center", 40))
            .set_duration(duration)
        )
        layers.append(title_clip)
    except Exception as e:
        log_err(f"{sid} → title text failed: {e} (continuing without title)")

    # Subtitles (bottom 15%)
    script_text = read_text(script_file)
    chunks = _chunk_text(script_text)
    subtitle_ok = True

    if chunks:
        chunk_dur = duration / len(chunks)
        for i, chunk in enumerate(chunks):
            try:
                sub = (
                    TextClip(
                        chunk,
                        fontsize=36,
                        color="white",
                        font=FONT_REGULAR,
                        size=(W - 80, int(H * 0.15)),
                        method="caption",
                        stroke_color="black",
                        stroke_width=1.5,
                    )
                    .set_position(("center", int(H * 0.85)))
                    .set_start(i * chunk_dur)
                    .set_duration(chunk_dur)
                )
                layers.append(sub)
            except Exception:
                if subtitle_ok:
                    log_err(f"{sid} → subtitle rendering failed, continuing without subtitles")
                    subtitle_ok = False
                break

    # Compose
    video = CompositeVideoClip(layers, size=(W, H)).set_audio(audio_clip)
    video.write_videofile(
        str(output_file),
        fps=config.FPS,
        codec="libx264",
        audio_codec="aac",
        logger=None,
    )
    audio_clip.close()


def run_video():
    """Build videos for all available audio files."""
    log_header("PHASE 4: Video Assembly")
    index = load_index()

    from tqdm import tqdm

    ok_entries = [e for e in index if e.get("status") == "ok"]

    # Also check for combined/split scripts
    script_files = sorted(Path(config.__file__).parent.joinpath("data", "scripts").glob("*_script.txt"))
    script_ids = {sf.stem.replace("_script", "") for sf in script_files}

    for sid in tqdm(sorted(script_ids), desc="Building videos"):
        out = video_path(sid)
        if out.exists():
            log_skip(f"{sid} video exists")
            continue

        if not audio_path(sid).exists():
            log_skip(f"{sid} no audio")
            continue

        # Determine kanda info from the sid
        parts = sid.split("_")
        kanda_key = parts[0]
        sarga_num_str = parts[1] if len(parts) > 1 else "1"
        try:
            sarga_num = int(sarga_num_str)
        except ValueError:
            sarga_num = 1

        kanda_name = config.KANDAS.get(kanda_key, {}).get("name", kanda_key)

        try:
            build_video(sid, kanda_key, sarga_num, kanda_name)
            log_ok(f"{sid} → {out.name}")
        except Exception as e:
            log_err(f"{sid} → {e}")


if __name__ == "__main__":
    run_video()
