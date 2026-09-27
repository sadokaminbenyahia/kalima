"""Speech-to-text: the student's spoken input (audio file) -> plain text."""

import sys
from pathlib import Path

# Make backend/ importable when this file is run directly as a script.
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from models.nemotron_client import ask_audio  # noqa: E402

# Anything shorter is treated as a failed transcription rather than passed on to dialogue.
MIN_TRANSCRIPTION_CHARS = 2
# Straight, curly and French quotes the model sometimes wraps its output in.
QUOTE_CHARS = "\"'“”‘’«»"

TRANSCRIBE_PROMPT = """Transcribe this audio exactly, word for word, in the language actually spoken.
Do not translate, summarize, correct or answer what is said.
Output only the transcribed words: no introduction such as "Here is the transcription:", no quotes,
no comments before or after."""


class TranscriptionError(RuntimeError):
    pass


def transcribe_audio(audio_path: str) -> str:
    # reasoning_budget=0: fast mode, this is on the live interaction path.
    text = ask_audio(TRANSCRIBE_PROMPT, audio_path, reasoning_budget=0)
    # Strip whitespace, then quotes, then the inner padding of e.g. « bonjour ».
    text = text.strip().strip(QUOTE_CHARS).strip()
    if len(text) < MIN_TRANSCRIPTION_CHARS:
        raise TranscriptionError(f"Transcription of {audio_path!r} is empty or too short: {text!r}")
    return text


if __name__ == "__main__":
    if len(sys.argv) not in (2, 4):
        sys.exit("Usage: python transcribe.py <audio_path> [<pdf_path> <part_index>]")
    # Windows consoles default to cp1252, which mangles accents and math characters.
    sys.stdout.reconfigure(encoding="utf-8")

    transcription = transcribe_audio(sys.argv[1])
    if len(sys.argv) == 2:
        print(transcription)
        sys.exit()

    # End-to-end: audio -> transcription -> dialogue turn on the given lesson part.
    from pipeline.dialogue import load_parts_cached, respond

    parts = load_parts_cached(sys.argv[2])
    part_index = int(sys.argv[3])
    if not 0 <= part_index < len(parts):
        sys.exit(f"part_index must be between 0 and {len(parts) - 1} (document has {len(parts)} parts)")
    reply = respond(parts[part_index], parts, transcription, history=[])
    print(f"--- Part {part_index + 1}: {parts[part_index]['title']} ---")
    print(f"Transcription: {transcription}")
    print(f"Intent: {reply['intent']}")
    print(f"Text: {reply['text']}")
