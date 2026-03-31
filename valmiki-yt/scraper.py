from __future__ import annotations
"""Phase 1: Scrape English prose translations from valmikiramayan.net.

The 'sans' pages (e.g. balasans1.htm) contain interleaved content:
  1. An introduction / chapter summary at the top
  2. For each verse: Sanskrit shloka → word-by-word meaning → English prose
  3. Footnotes / commentary paragraphs interspersed

Extraction strategy (derived from inspecting actual HTML source):
  - The pages are old-school HTML: content lives in <p>, <font>, <td> elements
  - We grab all visible text, then filter line-by-line:
      • Skip lines that are purely Devanagari (Unicode block 0900-097F)
      • Skip ITRANS transliteration lines (contain ā, ī, ū, ṃ, ḥ, etc.)
      • Skip verse-number citations like "1-1-1" or "|| 1 ||" or "५-१-२१"
      • Skip "Verse Locator" markers
      • Skip word-by-word glosses (lines with many '=' signs)
      • Keep clean English prose paragraphs
  - The introduction paragraph(s) appear before the first "Verse Locator"
"""

import re
import sys
import unicodedata

import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

import config
from utils import (
    log_ok, log_skip, log_err, log_header,
    now_iso, write_json, rate_limit,
    sarga_path, sarga_exists,
    load_index, save_index, upsert_index, print_status_table,
    SARGAS_DIR,
)

# ── Unicode / ITRANS detection ─────────────────────────────────────────────

# Devanagari Unicode range
_DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")

# Special diacritical characters used in ITRANS / romanised Sanskrit
_ITRANS_CHARS = set("āīūṃḥṇśṣṭḍṅñṛṝḷḹ")
_ITRANS_CHARS |= {c.upper() for c in _ITRANS_CHARS}

# Verse number patterns
_VERSE_NUM_RE = re.compile(
    r"^\s*\d+[\-\.]\s*$"                           # bare "1." or "1-"
    r"|^\s*\d+[\s;,]+\d*\s*\.?\s*$"                # "1; 2." compound verse nums
    r"|\|\|\s*\d+\s*\|\|"                           # "|| 1 ||"
    r"|^\s*[\d\-\.\s;,]+$"                          # lines that are only numbers
    r"|[\u0966-\u096F]"                              # Devanagari digits
)

_VERSE_LOCATOR_RE = re.compile(r"verse\s*locator", re.IGNORECASE)

# Word-by-word gloss lines have many "=" signs
_GLOSS_RE = re.compile(r"=")


def _is_devanagari_line(line: str) -> bool:
    """True if ≥40% of the non-space characters are Devanagari."""
    chars = [c for c in line if not c.isspace()]
    if not chars:
        return False
    dev = sum(1 for c in chars if _DEVANAGARI_RE.match(c))
    return dev / len(chars) > 0.4


def _is_itrans_line(line: str) -> bool:
    """True if the line contains ITRANS diacritical chars and looks like transliteration."""
    has_itrans = any(c in _ITRANS_CHARS for c in line)
    if not has_itrans:
        return False
    # Transliteration lines typically have many diacriticals relative to length
    count = sum(1 for c in line if c in _ITRANS_CHARS)
    # If more than 3 diacriticals in a short line, it's likely transliteration
    return count >= 3


def _is_gloss_line(line: str) -> bool:
    """Word-by-word meaning lines have many '=' separators."""
    return len(_GLOSS_RE.findall(line)) >= 3


def _is_verse_num_line(line: str) -> bool:
    return bool(_VERSE_NUM_RE.search(line))


def _is_verse_locator(line: str) -> bool:
    return bool(_VERSE_LOCATOR_RE.search(line))


def _is_boilerplate(line: str) -> bool:
    """Skip known boilerplate lines."""
    low = line.strip().lower()
    if not low:
        return True
    if low.startswith("comment :") or low.startswith("note :"):
        return False  # keep commentary
    if "converted to utf-8" in low:
        return True
    if "verse locator" in low:
        return True
    if low.startswith("top of page"):
        return True
    if "©" in low or "copyright" in low:
        return True
    if "edited by" in low and "rao" in low:
        return True
    if low.startswith("thus, this is the") or low.startswith("thus completes"):
        return True
    if re.match(r"^book\s+[ivxlcdm]+\s*:", low):
        return True
    if re.match(r"^chapter\s*\[sarga\]", low):
        return True
    if low == "introduction":
        return True
    # Footer lines like "Of Ayodhya : Chapter 1" or "Majesties : Chapter 5"
    if re.match(r"^.*:\s*chapter\s+\d+", low):
        return True
    # Stray chapter/sarga markers
    if re.match(r"^(sarga|chapter)\s+\d+\s*$", low):
        return True
    # "ityārṣe" colophon lines
    if "ityarse" in low or "ityārṣe" in low.lower():
        return True
    # Common colophon/closing fragments
    if "the work of a sage" in low:
        return True
    if "the oldest epic" in low:
        return True
    if re.match(r"^the\s+\d+(st|nd|rd|th)\s+(chapter|sarga)", low):
        return True
    if "first poem" in low and "mankind" in low:
        return True
    if re.match(r"^srimad\s+valmiki\s+ramayana", low):
        return True
    return False


def _clean_line(line: str) -> str:
    """Normalize whitespace."""
    return " ".join(line.split()).strip()


# ── Main extraction ───────────────────────────────────────────────────────

def _is_english_prose(line: str) -> bool:
    """
    Determine if a line is English prose translation (what we want to keep).
    
    English prose lines:
      - Are mostly ASCII/Latin characters
      - Contain actual English sentences (have spaces, common English words)
      - Don't contain '=' (word-by-word glosses)
      - Don't have excessive ITRANS diacriticals
      - Are reasonably long (>30 chars typically)
      - Don't start with a number followed by a period (verse numbering)
    """
    if not line or len(line) < 20:
        return False
    
    # Skip lines with Devanagari
    if _is_devanagari_line(line):
        return False
    
    # Skip gloss lines (word-by-word with = signs)
    if "=" in line:
        return False
    
    # Skip verse locators
    if _is_verse_locator(line):
        return False
    
    # Skip boilerplate
    if _is_boilerplate(line):
        return False
    
    # Skip lines that are mostly verse numbers / citations
    if _is_verse_num_line(line) and len(line) < 60:
        return False
    
    # Skip if line starts with a bare number like "1." or "1;"  (verse numbering)
    if re.match(r"^\d+[\.\;\,]\s", line):
        return False
    
    # Count ASCII letters vs total non-space chars
    non_space = [c for c in line if not c.isspace()]
    if not non_space:
        return False
    
    ascii_letters = sum(1 for c in non_space if c.isascii() and c.isalpha())
    ratio = ascii_letters / len(non_space)
    
    # English prose should be >60% ASCII letters
    if ratio < 0.6:
        return False
    
    # Skip ITRANS-heavy lines (transliteration)
    itrans_count = sum(1 for c in line if c in _ITRANS_CHARS)
    if itrans_count > 5 and itrans_count / len(line) > 0.05:
        return False
    
    # Should contain spaces (it's prose, not a single word)
    if " " not in line:
        return False
    
    # Should have at least a few words
    words = line.split()
    if len(words) < 4:
        return False
    
    return True


def extract_prose(html: str) -> tuple:
    """
    Extract (summary, translation_text) from a sans page's HTML.

    Returns:
        summary: The introductory paragraph(s) before the first verse.
        translation_text: All English prose paragraphs concatenated.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Remove script, style, and navigation elements
    for tag in soup(["script", "style", "select", "option"]):
        tag.decompose()

    # Get all text — the pages use nested tables/fonts, so get_text() is safest
    raw_text = soup.get_text(separator="\n")
    lines = raw_text.split("\n")

    summary_lines = []
    prose_lines = []
    found_first_verse = False
    in_intro = True

    for raw_line in lines:
        line = _clean_line(raw_line)
        if not line:
            continue

        # Detect first Verse Locator to separate intro from body
        if _is_verse_locator(line):
            if in_intro:
                in_intro = False
                found_first_verse = True
            continue

        if in_intro:
            # Before the first verse: collect the introduction/summary
            if _is_boilerplate(line):
                continue
            if _is_devanagari_line(line):
                continue
            if _is_english_prose(line):
                summary_lines.append(line)
        else:
            # After first verse: collect ONLY English prose translations
            if _is_english_prose(line):
                prose_lines.append(line)

    summary = " ".join(summary_lines).strip()
    translation = "\n\n".join(prose_lines).strip()

    return summary, translation


# ── Scraping logic ────────────────────────────────────────────────────────

def fetch_page(url: str) -> tuple:
    """Fetch a URL and return (status_code, html). Returns (0, '') on exception."""
    headers = {"User-Agent": config.USER_AGENT}
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        return resp.status_code, resp.text
    except requests.RequestException as e:
        return 0, str(e)


def scrape_sarga(kanda_key: str, sarga_num: int) -> dict:
    """Scrape a single sarga, return a sarga JSON dict."""
    sid = config.sarga_id(kanda_key, sarga_num)
    url = config.sarga_url(kanda_key, sarga_num)
    info = config.KANDAS[kanda_key]

    rate_limit("http", config.REQUEST_DELAY)
    status_code, html = fetch_page(url)

    if status_code != 200:
        log_err(f"{sid} → HTTP {status_code} from {url}")
        return {
            "id": sid,
            "kanda": info["name"],
            "kanda_key": kanda_key,
            "sarga_number": sarga_num,
            "title": f"{info['name']} - Sarga {sarga_num}",
            "summary": "",
            "translation_text": "",
            "word_count": 0,
            "source_url": url,
            "scraped_at": now_iso(),
            "status": "error",
            "error": f"HTTP {status_code}",
        }

    try:
        summary, translation = extract_prose(html)
    except Exception as e:
        log_err(f"{sid} → Parse error: {e}")
        return {
            "id": sid,
            "kanda": info["name"],
            "kanda_key": kanda_key,
            "sarga_number": sarga_num,
            "title": f"{info['name']} - Sarga {sarga_num}",
            "summary": "",
            "translation_text": "",
            "word_count": 0,
            "source_url": url,
            "scraped_at": now_iso(),
            "status": "error",
            "error": str(e),
        }

    word_count = len(translation.split()) if translation else 0

    if word_count < 10:
        log_err(f"{sid} → Only {word_count} words extracted (possible parse issue)")
        status = "error"
        error_msg = f"Only {word_count} words extracted"
    else:
        status = "ok"
        error_msg = ""

    result = {
        "id": sid,
        "kanda": info["name"],
        "kanda_key": kanda_key,
        "sarga_number": sarga_num,
        "title": f"{info['name']} - Sarga {sarga_num}",
        "summary": summary,
        "translation_text": translation,
        "word_count": word_count,
        "source_url": url,
        "scraped_at": now_iso(),
        "status": status,
    }
    if error_msg:
        result["error"] = error_msg

    return result


# ── Public API ────────────────────────────────────────────────────────────

def dry_run(kanda_filter: str | None = None):
    """Print all URLs that would be fetched, without fetching."""
    log_header("DRY RUN — URL validation")
    count = 0
    for kanda_key, sarga_num in config.all_sargas():
        if kanda_filter and kanda_key != kanda_filter:
            continue
        url = config.sarga_url(kanda_key, sarga_num)
        sid = config.sarga_id(kanda_key, sarga_num)
        print(f"  {sid}  →  {url}")
        count += 1
    print(f"\n  Total URLs: {count}")


def run_scrape(kanda_filter: str | None = None, resume: bool = False):
    """Scrape all sargas (or a single kanda). Idempotent: skips existing files."""
    log_header("PHASE 1: Scrape")
    index = load_index()
    lu = {e["id"]: e for e in index}

    sargas = list(config.all_sargas())
    if kanda_filter:
        sargas = [(k, n) for k, n in sargas if k == kanda_filter]

    if resume:
        # Only re-scrape items with status="error"
        sargas = [
            (k, n) for k, n in sargas
            if lu.get(config.sarga_id(k, n), {}).get("status") == "error"
        ]
        print(f"  Resuming {len(sargas)} errored sargas")

    for kanda_key, sarga_num in tqdm(sargas, desc="Scraping"):
        sid = config.sarga_id(kanda_key, sarga_num)

        # Idempotent: skip if already scraped successfully
        if not resume and sarga_exists(sid):
            log_skip(f"{sid} already exists")
            continue

        sarga_data = scrape_sarga(kanda_key, sarga_num)
        write_json(sarga_path(sid), sarga_data)

        # Update index
        index_entry = {
            "id": sid,
            "kanda": sarga_data["kanda"],
            "kanda_key": kanda_key,
            "sarga_number": sarga_num,
            "word_count": sarga_data["word_count"],
            "status": sarga_data["status"],
        }
        index = upsert_index(index, index_entry)

        if sarga_data["status"] == "ok":
            log_ok(f"{sid} ({sarga_data['word_count']} words)")
        # errors already logged in scrape_sarga

    save_index(index)
    print_status_table(index)


if __name__ == "__main__":
    # Quick test: scrape first sarga of each kanda
    if "--dry-run" in sys.argv:
        kf = None
        for i, a in enumerate(sys.argv):
            if a == "--kanda" and i + 1 < len(sys.argv):
                kf = sys.argv[i + 1]
        dry_run(kf)
    else:
        run_scrape()
