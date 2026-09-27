"""Document extraction: PDF/image pages -> text + spoken-friendly descriptions of visuals."""

import re
import sys
import tempfile
from pathlib import Path

import pymupdf

# Make backend/ importable when this file is run directly as a script.
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from models.nemotron_client import ask_image  # noqa: E402

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}
RENDER_DPI = 150
# Extraction runs once at upload, not during the live lesson, so it can afford thinking mode.
# Without it the model drops or garbles formulas when converting them to words.
EXTRACT_REASONING_BUDGET = 2048
# Reasoning tokens plus a dense page's transcription must both fit.
EXTRACT_MAX_TOKENS = 8192

# Degenerate-output detection: the model sometimes emits <unk> runs or loops on a short token.
UNK_MAX_COUNT = 3
# A 1-5 char unit repeated 10+ times in a row, e.g. "abababab..." or "the the the ...".
REPEAT_RUN_RE = re.compile(r"(.{1,5}?)\1{9,}", re.DOTALL)
# Flag if repeated runs cover this share of the text, or if any single run is this long.
REPEAT_MAX_FRACTION = 0.3
REPEAT_MAX_RUN = 30
UNCERTAIN_MARKER = "[EXTRACTION INCERTAINE]"
# Fragments of EXTRACT_PROMPT that must never appear in a page's output (prompt leakage).
PROMPT_LEAK_MARKERS = (
    "Output only the transcription",
    "DIAGRAMS, CHARTS, TABLES",
    "Replace every formula with a line starting",
    "Transcribe all prose text on the page faithfully",
)

EXTRACT_PROMPT = """You are preparing a course page for a blind student. The result will be read aloud.

1. TEXT: Transcribe all prose text on the page faithfully, in reading order, in the page's original
   language. Keep headings, lists and paragraphs. Do not summarize, skip, or correct anything.

2. FORMULAS: Never write a formula with symbols, fractions, exponents or LaTeX. Replace every formula
   with a line starting "[Formula]" that says the complete formula in words, the way a teacher would read
   it aloud. Keep every variable, number and operation exactly as printed, including the left-hand side
   of an equation and the word "equals".

3. DIAGRAMS, CHARTS, TABLES: Replace each with a paragraph starting "[Figure]", "[Chart]" or "[Table]".
   - Start with one sentence on what it shows and why it is there.
   - Then the parts and how they relate, in a logical order (the order of a process, cause to effect).
     Describe meaning, not layout: avoid position words unless position matters.
   - Mention a label only if it is actually printed in the image, attached to the element it is next to.
     Do not invent or repeat labels.
   - Charts: what the axes represent, the overall trend, and key values.
   - Tables: what the columns are, then read the rows naturally.

Output only the transcription with these descriptions inline where each visual appears.
No preamble or closing remarks."""


def render_pdf_to_images(pdf_path: str) -> list[str]:
    """Render each PDF page to a PNG in a temp directory. Images are returned as-is."""
    if Path(pdf_path).suffix.lower() in IMAGE_EXTENSIONS:
        return [pdf_path]

    out_dir = Path(tempfile.mkdtemp(prefix="kalima_pages_"))
    paths = []
    with pymupdf.open(pdf_path) as doc:
        for i, page in enumerate(doc, start=1):
            out_path = out_dir / f"page_{i:03d}.png"
            page.get_pixmap(dpi=RENDER_DPI).save(out_path)
            paths.append(str(out_path))
    return paths


def extract_page(image_path: str) -> str:
    return ask_image(
        EXTRACT_PROMPT, image_path,
        reasoning_budget=EXTRACT_REASONING_BUDGET, max_tokens=EXTRACT_MAX_TOKENS,
    )


def leaks_prompt(text: str) -> bool:
    """True if the output echoes the extraction instructions instead of page content."""
    # The prompt wraps lines, so a leaked fragment may contain newlines and indentation.
    normalized = " ".join(text.split()).lower()
    return any(marker.lower() in normalized for marker in PROMPT_LEAK_MARKERS)


def is_degenerate(text: str) -> bool:
    """True if the output looks like model garbage (<unk> runs, a short token looping, leaked
    prompt instructions) rather than content."""
    text = text.strip()
    if not text:
        return True
    if text.count("<unk>") > UNK_MAX_COUNT:
        return True
    if leaks_prompt(text):
        return True

    repeated_chars = 0
    for match in REPEAT_RUN_RE.finditer(text):
        unit = match.group(1)
        # Dotted leaders, rules like "-----" and whitespace are legitimate layout, not loops.
        if not any(c.isalnum() for c in unit):
            continue
        if len(match.group(0)) // len(unit) >= REPEAT_MAX_RUN:
            return True
        repeated_chars += len(match.group(0))
    return repeated_chars / len(text) > REPEAT_MAX_FRACTION


def _extract_page_checked(page_number: int, image_path: str) -> str:
    """Extract a page, retrying once with a fresh call if the output is degenerate."""
    text = extract_page(image_path)
    if not is_degenerate(text):
        return text

    print(f"[extract] Page {page_number}: degenerate output, retrying once...", flush=True)
    text = extract_page(image_path)
    if not is_degenerate(text):
        return text

    print(f"[extract] WARNING: page {page_number} still degenerate after retry, marked {UNCERTAIN_MARKER}", flush=True)
    return f"{UNCERTAIN_MARKER}\n{text}"


def extract_document(file_path: str) -> str:
    pages = [
        _extract_page_checked(n, path)
        for n, path in enumerate(render_pdf_to_images(file_path), start=1)
    ]
    return "".join(f"\n\n--- Page {n} ---\n\n{text}" for n, text in enumerate(pages, start=1)).strip()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage: python extract.py <file.pdf|file.png|file.jpg>")
    # Windows consoles default to cp1252, which mangles accents and math characters.
    sys.stdout.reconfigure(encoding="utf-8")
    print(extract_document(sys.argv[1]))
