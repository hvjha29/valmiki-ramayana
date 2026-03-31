# valmiki-yt

A Python pipeline that scrapes English prose translations of Valmiki Ramayana from [valmikiramayan.net](https://www.valmikiramayan.net/utf8/) and converts each chapter (sarga) into a YouTube-ready narration video.

**Personal/educational project.**

## Credit

All prose translations are by **Desiraju Hanumanta Rao** and contributors at [valmikiramayan.net](https://www.valmikiramayan.net). This project is for personal and educational use only.

## Pipeline Phases

| Phase | Command | Description |
|-------|---------|-------------|
| 1 | `--scrape` | Scrape 534 sargas across 6 kandas |
| 2 | `--scripts` | Generate narration scripts via Claude API |
| 3 | `--audio` | Text-to-speech via gTTS |
| 4 | `--video` | Assemble portrait videos via moviepy |
| 5 | `--metadata` | Generate YouTube metadata via Claude API |

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# System dependency for text overlays in videos (macOS):
brew install imagemagick

# On Ubuntu/Debian:
# sudo apt-get install imagemagick

# Validate all 534 URLs first (no network requests)
python run.py --scrape --dry-run

# Validate URLs for a single kanda
python run.py --scrape --dry-run --kanda baala

# Scrape a single kanda
python run.py --scrape --kanda baala

# Scrape everything (takes ~20 min with 2s delay)
python run.py --scrape

# Run all phases
export ANTHROPIC_API_KEY=your_key_here
python run.py --all

# Check pipeline status
python run.py --status

# Re-run only failed items
python run.py --resume
```

## URL Pattern Discovery

The URL pattern differs from what you'd expect:

| Kanda | Directory | File Prefix | Example |
|-------|-----------|-------------|---------|
| Bala | `baala/` | `bala` | `balasans1.htm` |
| Ayodhya | `ayodhya/` | `ayodhya` | `ayodhyasans1.htm` |
| Aranya | `aranya/` | `aranya` | `aranyasans1.htm` |
| Kishkindha | `kish/` | `kishkindha` | `kishkindhasans1.htm` |
| Sundara | `sundara/` | `sundara` | `sundarasans1.htm` |
| Yuddha | `yuddha/` | `yuddha` | `yuddhasans1.htm` |

**Key gotchas:**
- Bala Kanda: directory is `baala/` but file prefix is `bala` (not `baala`)
- Kishkindha Kanda: directory is `kish/` but file prefix is `kishkindha` (not `kish`)

## Project Structure

```
valmiki-yt/
├── run.py              # CLI entry point
├── scraper.py          # Phase 1: Web scraping
├── script_gen.py       # Phase 2: Claude narration scripts
├── tts.py              # Phase 3: gTTS audio
├── video_builder.py    # Phase 4: moviepy video assembly
├── metadata_gen.py     # Phase 5: YouTube metadata
├── utils.py            # Shared helpers
├── config.py           # Kanda definitions, URL patterns
├── assets/             # Background images (user-provided)
│   ├── bg_default.jpg
│   └── bg_{kanda}.jpg
├── data/
│   ├── index.json      # Master index (source of truth)
│   ├── sargas/         # Scraped chapter JSON files
│   ├── scripts/        # Narration scripts
│   ├── audio/          # MP3 files
│   ├── videos/         # MP4 files
│   └── metadata/       # YouTube metadata JSON
├── requirements.txt
└── README.md
```

## Audio Upgrade Note

gTTS is placeholder quality. For channel-quality audio, switch to **ElevenLabs**:
- Recommended voices: "Clyde" or "Adam" (gravitas)
- Modify `tts.py` to use the ElevenLabs SDK

## Environment Variables

- `ANTHROPIC_API_KEY` — Required for Phases 2 and 5
- `IMAGEMAGICK_BINARY` — (Optional) Path to `convert` binary if auto-detection fails

## Data Model

Each sarga is saved as JSON:

```json
{
  "id": "baala_001",
  "kanda": "Bala Kanda",
  "kanda_key": "baala",
  "sarga_number": 1,
  "title": "Bala Kanda - Sarga 1",
  "summary": "...",
  "translation_text": "...",
  "word_count": 450,
  "source_url": "...",
  "scraped_at": "2026-03-31T...",
  "status": "ok"
}
```

## Extending

To add Uttara Kanda (Book 7), simply add an entry to `KANDAS` in `config.py`:

```python
"uttara": {
    "name": "Uttara Kanda",
    "dir": "uttara",
    "file_prefix": "uttara",  # verify actual filename first!
    "sarga_count": 111,
},
```
