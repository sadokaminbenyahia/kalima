"""Lesson segmentation: extracted document text -> ordered list of teachable parts."""

import json
import re
import sys
from pathlib import Path
from typing import Any, Callable

# Make backend/ importable when this file is run directly as a script.
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from models.nemotron_client import ask_text  # noqa: E402
from pipeline.extract import extract_document  # noqa: E402

# The answer repeats the whole document verbatim plus JSON overhead, so the default
# fast-mode limit (1024) would truncate it. Thinking stays off: this needs no deep reasoning.
SEGMENT_MAX_TOKENS = 16384

# Leading/trailing ```json fences the model sometimes adds despite instructions.
CODE_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)

SEGMENT_PROMPT = """You are splitting a course document into lesson parts for a tutor who will explain them
to a blind student one at a time.

Each part must be a coherent teaching chunk: a natural topic or sub-topic. Decide from the content,
not from page boundaries: a page may be its own part, several short pages may merge into one part,
and one long page may split into two. A part is never a single sentence.

Rules:
- Keep the parts in the document's original order and cover the whole document. Skip nothing.
- Copy each part's text VERBATIM from the document. Do not summarize, rephrase, correct or translate.
- Lines starting with [Figure], [Formula], [Chart], [Table] or [EXTRACTION INCERTAINE] must be copied
  in full, exactly as written, inside the part they belong to. They are the student's only access
  to that content.
- Leave out the "--- Page N ---" separator lines; they are not course content.
- "title" is a short name for the part, in the document's language.

Output strict JSON only: a JSON array where each item is {"title": "...", "text": "..."}.
No markdown code fences, no text before or after the array.

DOCUMENT:
"""


class SegmentationError(RuntimeError):
    pass


def parse_model_json(response: str, is_valid: Callable[[Any], bool], brackets: str = "[]") -> Any | None:
    """Leniently parse JSON from a model answer; return the first candidate passing is_valid, or None.

    Tries the raw text, then with ```json fences stripped, then the outermost span delimited by
    brackets ("[]" for an array, "{}" for an object) in case of prose before/after it.
    """
    candidates = [response, CODE_FENCE_RE.sub("", response)]
    start, end = response.find(brackets[0]), response.rfind(brackets[1])
    if start != -1 and end > start:
        candidates.append(response[start:end + 1])

    for candidate in candidates:
        try:
            # strict=False tolerates raw newlines inside strings, which the model often emits.
            parsed = json.loads(candidate, strict=False)
        except json.JSONDecodeError:
            continue
        if is_valid(parsed):
            return parsed
    return None


def _is_valid(parts) -> bool:
    return (
        isinstance(parts, list)
        and len(parts) > 0
        and all(
            isinstance(p, dict)
            and isinstance(p.get("title"), str)
            and isinstance(p.get("text"), str)
            and p["text"].strip()
            for p in parts
        )
    )


def segment_document(extracted_text: str) -> list[dict]:
    prompt = SEGMENT_PROMPT + extracted_text
    for attempt in (1, 2):
        response = ask_text(prompt, reasoning_budget=0, max_tokens=SEGMENT_MAX_TOKENS)
        parts = parse_model_json(response, _is_valid, "[]")
        if parts is not None:
            return [
                {"index": i, "title": p["title"].strip(), "text": p["text"].strip()}
                for i, p in enumerate(parts)
            ]
        if attempt == 1:
            print("[segment] Could not parse model output as a JSON list of parts, retrying once...", flush=True)

    raise SegmentationError(
        f"Model output was not a valid JSON list of parts after 2 attempts. "
        f"Last response starts with: {response[:500]!r}"
    )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage: python segment.py <file.pdf|file.png|file.jpg>")
    # Windows consoles default to cp1252, which mangles accents and math characters.
    sys.stdout.reconfigure(encoding="utf-8")
    parts = segment_document(extract_document(sys.argv[1]))
    print("".join(f"\n\n--- Part {p['index'] + 1}: {p['title']} ---\n\n{p['text']}" for p in parts).strip())
