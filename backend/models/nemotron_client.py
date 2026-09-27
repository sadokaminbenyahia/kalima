"""Thin wrapper around NVIDIA's hosted Nemotron 3 Nano Omni chat-completions API.

Request shapes follow the model's API reference:
https://docs.nvidia.com/nim/vision-language-models/1.7.0/examples/nemotron-3-nano-omni-30b-a3b-reasoning/api.html
"""

import base64
import mimetypes
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

# backend/.env (one level up from models/); falls back to any .env found from the CWD.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
load_dotenv()

API_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
MODEL = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"
TIMEOUT_SECONDS = 120

# On 503, retry with exponential backoff: 2s, 4s, 8s.
MAX_RETRIES = 3
RETRY_BASE_DELAY_SECONDS = 2

DEFAULT_MAX_TOKENS = 1024
# Reasoning tokens count against max_tokens; too low a limit yields an empty answer.
THINKING_MAX_TOKENS = 8192


class NemotronError(RuntimeError):
    pass


def _api_key() -> str:
    key = os.getenv("NVIDIA_API_KEY")
    if not key:
        raise NemotronError("NVIDIA_API_KEY is not set. Add it to backend/.env.")
    return key


# mimetypes varies by OS (e.g. audio/x-wav on Windows), so pin the formats the model accepts.
MIME_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".flac": "audio/flac",
    # Browser MediaRecorder output (Opus audio); mimetypes would say video/webm.
    ".webm": "audio/webm",
}


def _to_data_url(path: str) -> str:
    """Encode a local file as a data: URL, e.g. data:image/png;base64,...."""
    mime = MIME_TYPES.get(Path(path).suffix.lower()) or mimetypes.guess_type(path)[0]
    if mime is None:
        raise NemotronError(f"Cannot determine the media type of {path!r}")
    with open(path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _resolve_media(source: str) -> str:
    """Pass through http(s)/data: URLs; encode anything else as a local file."""
    if source.startswith(("http://", "https://", "data:")):
        return source
    if not os.path.isfile(source):
        raise NemotronError(f"File not found: {source!r}")
    return _to_data_url(source)


def _chat(messages: list, reasoning_budget: int = 0, max_tokens: int | None = None) -> str:
    """Send a chat request and return the final answer text.

    reasoning_budget=0 runs in instruct (non-thinking) mode for fast responses.
    A positive value turns thinking on, capped at that many reasoning tokens.
    """
    thinking = reasoning_budget > 0
    payload = {
        "model": MODEL,
        "messages": messages,
        "max_tokens": max_tokens or (THINKING_MAX_TOKENS if thinking else DEFAULT_MAX_TOKENS),
        "temperature": 0.6 if thinking else 0.2,
        "top_p": 0.95,
        "stream": False,
        # Thinking is on by default for this model, so it must be disabled explicitly.
        "chat_template_kwargs": {"enable_thinking": thinking},
    }
    if thinking:
        payload["reasoning_budget"] = reasoning_budget

    headers = {
        "Authorization": f"Bearer {_api_key()}",
        "Accept": "application/json",
    }
    for attempt in range(MAX_RETRIES + 1):
        try:
            response = requests.post(API_URL, headers=headers, json=payload, timeout=TIMEOUT_SECONDS)
        except requests.RequestException as e:
            raise NemotronError(f"Request to NVIDIA API failed: {e}") from e
        if response.status_code != 503:
            break
        if attempt == MAX_RETRIES:
            raise NemotronError(
                f"NVIDIA API unavailable (503) after {MAX_RETRIES} retries: {response.text[:500]}"
            )
        delay = RETRY_BASE_DELAY_SECONDS * 2 ** attempt
        print(f"[nemotron] 503 Service Unavailable, retry {attempt + 1}/{MAX_RETRIES} in {delay}s...", flush=True)
        time.sleep(delay)

    if not response.ok:
        raise NemotronError(f"NVIDIA API returned {response.status_code}: {response.text[:500]}")

    choice = response.json()["choices"][0]
    content = choice["message"].get("content")
    if choice.get("finish_reason") == "length":
        print(f"[nemotron] WARNING: response truncated at max_tokens={payload['max_tokens']}", flush=True)
    if not content:
        raise NemotronError("Empty response content (max_tokens may be too low for reasoning).")
    return content.strip()


def ask_text(prompt: str, reasoning_budget: int = 0, max_tokens: int | None = None) -> str:
    messages = [{"role": "user", "content": prompt}]
    return _chat(messages, reasoning_budget, max_tokens)


def ask_image(
    prompt: str, image_url_or_base64: str, reasoning_budget: int = 0, max_tokens: int | None = None
) -> str:
    """image_url_or_base64: a public URL, a data: URL, or a local JPEG/PNG path."""
    messages = [{
        "role": "user",
        "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": _resolve_media(image_url_or_base64)}},
        ],
    }]
    return _chat(messages, reasoning_budget, max_tokens)


def ask_audio(prompt: str, audio_path: str, reasoning_budget: int = 0) -> str:
    """audio_path: a local WAV/MP3/FLAC file, or a public/data: URL."""
    messages = [{
        "role": "user",
        "content": [
            {"type": "text", "text": prompt},
            {"type": "audio_url", "audio_url": {"url": _resolve_media(audio_path)}},
        ],
    }]
    return _chat(messages, reasoning_budget)


if __name__ == "__main__":
    print(ask_text("Hello, what can you do?"))
