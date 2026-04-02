"""
Configuration for Valmiki Ramayana YouTube pipeline.

IMPORTANT: URL patterns were verified by inspecting the actual directory
listings on valmikiramayan.net. The file prefix in the URL differs from the
directory name for two kandas:
  - baala/ directory uses 'bala' as the file prefix
  - kish/ directory uses 'kishkindha' as the file prefix
All other kandas use the directory name as the file prefix.
"""

BASE_URL = "https://www.valmikiramayan.net/utf8"

# Kanda definitions: key → (display_name, dir_name, file_prefix, sarga_count)
# dir_name  = folder name in the URL path
# file_prefix = prefix used in the .htm filename (e.g. balasans1.htm)
KANDAS = {
    "baala": {
        "name": "Bala Kanda",
        "dir": "baala",
        "file_prefix": "bala",
        "sarga_count": 77,
    },
    "ayodhya": {
        "name": "Ayodhya Kanda",
        "dir": "ayodhya",
        "file_prefix": "ayodhya",
        "sarga_count": 119,
    },
    "aranya": {
        "name": "Aranya Kanda",
        "dir": "aranya",
        "file_prefix": "aranya",
        "sarga_count": 75,
    },
    "kish": {
        "name": "Kishkindha Kanda",
        "dir": "kish",
        "file_prefix": "kishkindha",
        "sarga_count": 67,
    },
    "sundara": {
        "name": "Sundara Kanda",
        "dir": "sundara",
        "file_prefix": "sundara",
        "sarga_count": 68,
    },
    "yuddha": {
        "name": "Yuddha Kanda",
        "dir": "yuddha",
        "file_prefix": "yuddha",
        "sarga_count": 128,
    },
}

TOTAL_SARGAS = sum(k["sarga_count"] for k in KANDAS.values())  # 534

# Request settings
USER_AGENT = "Mozilla/5.0 (research/personal use)"
REQUEST_DELAY = 2  # seconds between HTTP requests

# ── Hugging Face Inference API ─────────────────────────────────────────────
HF_MODEL_PRIMARY = "Qwen/Qwen2.5-72B-Instruct"
HF_MODEL_FALLBACKS = [
    "meta-llama/Llama-3.1-8B-Instruct",
    "mistralai/Mistral-7B-Instruct-v0.2",
    "HuggingFaceH4/zephyr-7b-beta",
]
HF_MAX_NEW_TOKENS = 2048
HF_TEMPERATURE = 0.7
HF_TOP_P = 0.9
HF_REQUEST_DELAY = 2.0  # seconds between HF API calls (free-tier rate limits)

# Input truncation: keeps requests small for free-tier rate limits.
# Even though Qwen2.5-72B has 128K context, smaller inputs = faster + cheaper.
# 5500 chars ≈ 1500 tokens input, leaving ample room for output.
HF_MAX_INPUT_CHARS = 5500

# Video settings
VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920
FPS = 24

# Script word-count thresholds
SCRIPT_MIN_WORDS = 300
SCRIPT_MAX_WORDS = 1200

# TTS settings
TTS_LANG = "en"
TTS_SLOW = False

# ── Per-kanda expected names (for script quality / hallucination check) ────
# If fewer than 3 of these appear in a generated script, flag low_confidence.
KANDA_EXPECTED_NAMES = {
    "baala": [
        "Rama", "Vishwamitra", "Dasharatha", "Valmiki", "Sita",
        "Lakshmana", "Kausalya", "Tataka", "Maricha", "Janaka",
        "Bharata", "Shatrughna", "Narada", "Ayodhya",
    ],
    "ayodhya": [
        "Rama", "Sita", "Lakshmana", "Dasharatha", "Kaikeyi",
        "Bharata", "Kausalya", "Sumitra", "Guha", "Ayodhya",
        "Chitrakuta", "Manthara", "Sumantra",
    ],
    "aranya": [
        "Rama", "Sita", "Lakshmana", "Ravana", "Surpanakha",
        "Jatayu", "Maricha", "Agastya", "Khara", "Panchavati",
        "Dandaka",
    ],
    "kish": [
        "Rama", "Sugriva", "Hanuman", "Vali", "Lakshmana",
        "Tara", "Angada", "Kishkindha", "Rishyamuka", "Sita",
    ],
    "sundara": [
        "Hanuman", "Sita", "Rama", "Ravana", "Lanka",
        "Lakshmana", "Trijata", "Indrajit", "Ashoka",
    ],
    "yuddha": [
        "Rama", "Ravana", "Lakshmana", "Hanuman", "Sita",
        "Vibhishana", "Indrajit", "Kumbhakarna", "Sugriva",
        "Lanka", "Angada", "Mandodari",
    ],
}


def sarga_url(kanda_key: str, sarga_num: int) -> str:
    """Build the full URL for a sarga's Sanskrit+English translation page."""
    k = KANDAS[kanda_key]
    return (
        f"{BASE_URL}/{k['dir']}/sarga{sarga_num}/"
        f"{k['file_prefix']}sans{sarga_num}.htm"
    )


def sarga_id(kanda_key: str, sarga_num: int) -> str:
    """Canonical ID like 'baala_001'."""
    return f"{kanda_key}_{sarga_num:03d}"


def all_sargas():
    """Yield (kanda_key, sarga_num) for every sarga."""
    for kanda_key, info in KANDAS.items():
        for n in range(1, info["sarga_count"] + 1):
            yield kanda_key, n
