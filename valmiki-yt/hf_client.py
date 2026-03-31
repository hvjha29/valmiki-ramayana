"""
Hugging Face Inference API client with automatic model fallback.

Supports two modes:
  1. huggingface_hub InferenceClient (preferred — handles chat templates)
  2. Raw REST API fallback (if huggingface_hub not installed)

The --model CLI flag pins a specific model to skip the fallback chain.
"""
from __future__ import annotations

import os
import time
from typing import Optional

import requests as req_lib

import config


# ── Model alias map (short name → full HF model ID) ─────────────────────────

MODEL_ALIASES = {
    "mistral": config.HF_MODEL_PRIMARY,
    "zephyr": "HuggingFaceH4/zephyr-7b-beta",
    "phi": "microsoft/Phi-3-mini-4k-instruct",
    "gemma": "google/gemma-2-2b-it",
    "falcon": "tiiuae/falcon-7b-instruct",
}


def resolve_model_name(name: str) -> str:
    """Resolve a short alias like 'mistral' to the full HF model path."""
    return MODEL_ALIASES.get(name.lower(), name)


class HFClient:
    """
    Wraps the HF Inference API for text generation.
    Tries primary model first, then falls back through alternatives.
    Pass pinned_model= to skip the fallback chain entirely.
    """

    REST_URL = "https://api-inference.huggingface.co/models/{model}"

    def __init__(self, token: Optional[str] = None, pinned_model: Optional[str] = None):
        self.token = token or os.environ.get("HF_TOKEN", "")
        if not self.token:
            raise EnvironmentError(
                "No HF token. Set HF_TOKEN env var or pass token= to HFClient()."
            )

        # Build model list
        if pinned_model:
            resolved = resolve_model_name(pinned_model)
            self.models = [resolved]
            print(f"  📌 Pinned to model: {resolved}")
        else:
            self.models = [config.HF_MODEL_PRIMARY] + config.HF_MODEL_FALLBACKS

        self._active_model = self.models[0]
        self._last_call: float = 0.0

        # Try to use huggingface_hub for better chat template handling
        self._hf_client = None
        try:
            from huggingface_hub import InferenceClient
            self._hf_client = InferenceClient(token=self.token)
        except ImportError:
            print("  ℹ️  huggingface_hub not installed — using REST API")

    # ── Rate limiting ────────────────────────────────────────────────────

    def _rate_limit(self):
        elapsed = time.time() - self._last_call
        if elapsed < config.HF_REQUEST_DELAY:
            time.sleep(config.HF_REQUEST_DELAY - elapsed)
        self._last_call = time.time()

    # ── Prompt builders ──────────────────────────────────────────────────

    @staticmethod
    def _chat_messages(system: str, user: str) -> list[dict]:
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

    @staticmethod
    def _raw_prompt(system: str, user: str, model: str) -> str:
        m = model.lower()
        if "mistral" in m:
            return f"<s>[INST] {system}\n\n{user} [/INST]"
        if "zephyr" in m:
            return f"<|system|>\n{system}</s>\n<|user|>\n{user}</s>\n<|assistant|>\n"
        if "phi" in m:
            return f"<|system|>\n{system}<|end|>\n<|user|>\n{user}<|end|>\n<|assistant|>\n"
        if "gemma" in m:
            return f"<start_of_turn>user\n{system}\n\n{user}<end_of_turn>\n<start_of_turn>model\n"
        if "falcon" in m:
            return f"System: {system}\nUser: {user}\nAssistant:"
        return f"### System:\n{system}\n\n### User:\n{user}\n\n### Assistant:\n"

    # ── Hub client call ──────────────────────────────────────────────────

    def _call_hub(self, model: str, system: str, user: str) -> Optional[str]:
        if not self._hf_client:
            return None
        try:
            self._rate_limit()
            # Try chat_completion (works for instruction-tuned models)
            resp = self._hf_client.chat_completion(
                model=model,
                messages=self._chat_messages(system, user),
                max_tokens=config.HF_MAX_NEW_TOKENS,
                temperature=config.HF_TEMPERATURE,
                top_p=config.HF_TOP_P,
            )
            text = resp.choices[0].message.content
            if text and len(text.strip()) > 50:
                return text.strip()
        except Exception as e:
            err = str(e).lower()
            if "loading" in err or "503" in err:
                print(f"    ⏳ {model} loading, waiting 30s...")
                time.sleep(30)
            elif "rate" in err or "429" in err:
                print(f"    ⚠ Rate limited, waiting 10s...")
                time.sleep(10)
            elif "not supported" in err or "404" in err:
                pass  # model doesn't support chat, will fall through to REST
            else:
                print(f"    ✗ hub error: {str(e)[:150]}")
        return None

    # ── REST fallback ────────────────────────────────────────────────────

    def _call_rest(self, model: str, system: str, user: str) -> Optional[str]:
        url = self.REST_URL.format(model=model)
        headers = {"Authorization": f"Bearer {self.token}"}
        prompt = self._raw_prompt(system, user, model)

        payload = {
            "inputs": prompt,
            "parameters": {
                "max_new_tokens": config.HF_MAX_NEW_TOKENS,
                "temperature": config.HF_TEMPERATURE,
                "top_p": config.HF_TOP_P,
                "repetition_penalty": 1.1,
                "do_sample": True,
            },
            "options": {"wait_for_model": True, "use_cache": False},
        }
        try:
            self._rate_limit()
            r = req_lib.post(url, headers=headers, json=payload, timeout=120)

            if r.status_code == 503:
                wait = 30
                try:
                    wait = min(r.json().get("estimated_time", 30), 60)
                except Exception:
                    pass
                print(f"    ⏳ {model} loading, waiting {wait:.0f}s...")
                time.sleep(wait)
                self._rate_limit()
                r = req_lib.post(url, headers=headers, json=payload, timeout=120)

            if r.status_code == 429:
                print(f"    ⚠ Rate limited on {model}")
                time.sleep(10)
                return None

            if r.status_code != 200:
                print(f"    ✗ HTTP {r.status_code}: {r.text[:200]}")
                return None

            result = r.json()
            if isinstance(result, list) and result:
                gen = result[0].get("generated_text", "")
            elif isinstance(result, dict):
                gen = result.get("generated_text", "")
            else:
                return None

            # Strip prompt prefix
            if gen.startswith(prompt):
                gen = gen[len(prompt):]
            return gen.strip() if len(gen.strip()) > 50 else None

        except req_lib.exceptions.Timeout:
            print(f"    ✗ {model} timed out")
            return None
        except Exception as e:
            print(f"    ✗ {model}: {e}")
            return None

    # ── Public API ───────────────────────────────────────────────────────

    def generate(self, system_prompt: str, user_prompt: str) -> Optional[str]:
        """Generate text. Tries each model in order until one succeeds."""
        for model in self.models:
            print(f"  🤖 Trying {model}...")

            # Hub client first
            result = self._call_hub(model, system_prompt, user_prompt)
            if result:
                self._active_model = model
                return result

            # REST fallback
            result = self._call_rest(model, system_prompt, user_prompt)
            if result:
                self._active_model = model
                return result

            if len(self.models) > 1:
                print(f"    ↳ Falling back...")

        print("  ✗ All models failed")
        return None

    @property
    def active_model(self) -> str:
        return self._active_model

    def test_connection(self) -> bool:
        """Quick test to verify the token works."""
        print("Testing HF Inference API connection...")
        result = self.generate(
            "You are a helpful assistant. Respond briefly.",
            "Say exactly: 'Connection successful.'",
        )
        if result:
            print(f"\n  ✓ Connected via {self._active_model}")
            print(f"  Response: {result[:200]}")
            return True
        print("\n  ✗ All models unreachable")
        return False
