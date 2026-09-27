"""KALIMA backend API: upload a course PDF, walk through its parts, ask questions by voice."""

import os
import tempfile
import uuid
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

load_dotenv(Path(__file__).resolve().parent / ".env")

from models.nemotron_client import NemotronError  # noqa: E402
from pipeline.dialogue import DialogueError, respond  # noqa: E402
from pipeline.extract import extract_document  # noqa: E402
from pipeline.segment import SegmentationError, segment_document  # noqa: E402
from pipeline.transcribe import TranscriptionError, transcribe_audio  # noqa: E402

app = FastAPI(title="KALIMA")

# Wide open for the hackathon demo; restrict origins/methods/headers before any real deployment.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# lesson_id -> {"parts": [...], "history": [{"student_input": ..., "intent": ...}, ...]}.
# In-memory only: lost on restart, not shared between worker processes.
lessons: dict[str, dict] = {}


class ExplainRequest(BaseModel):
    lesson_id: str
    part_index: int


def _save_upload(upload: UploadFile, suffix: str) -> str:
    """Write an upload to a temp file and return its path. The caller deletes it.

    The suffix matters: nemotron_client picks the audio MIME type from the file extension.
    """
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(upload.file.read())
        return tmp.name


def _get_lesson(lesson_id: str, part_index: int) -> dict:
    lesson = lessons.get(lesson_id)
    if lesson is None:
        raise HTTPException(status_code=404, detail=f"Unknown lesson_id: {lesson_id}")
    if not 0 <= part_index < len(lesson["parts"]):
        raise HTTPException(
            status_code=400,
            detail=f"part_index must be between 0 and {len(lesson['parts']) - 1}, got {part_index}",
        )
    return lesson


# Endpoints are plain `def` so FastAPI runs the blocking model calls in its threadpool.
@app.post("/upload")
def upload(file: UploadFile = File(...)):
    if Path(file.filename or "").suffix.lower() != ".pdf":
        raise HTTPException(status_code=400, detail="Only PDF files are supported for now (.pdf).")

    pdf_path = _save_upload(file, ".pdf")
    try:
        parts = segment_document(extract_document(pdf_path))
    except (NemotronError, SegmentationError) as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    finally:
        os.unlink(pdf_path)

    lesson_id = str(uuid.uuid4())
    lessons[lesson_id] = {"parts": parts, "history": []}
    return {"lesson_id": lesson_id, "parts": parts}


@app.post("/explain")
def explain(request: ExplainRequest):
    part = _get_lesson(request.lesson_id, request.part_index)["parts"][request.part_index]
    return {"text": part["text"], "title": part["title"]}


@app.post("/ask")
def ask(lesson_id: str = Form(...), part_index: int = Form(...), audio: UploadFile = File(...)):
    lesson = _get_lesson(lesson_id, part_index)
    parts = lesson["parts"]

    audio_path = _save_upload(audio, Path(audio.filename or "").suffix.lower() or ".wav")
    try:
        transcription = transcribe_audio(audio_path)
        result = respond(parts[part_index], parts, transcription, lesson["history"])
    # NemotronError too: API/network failures and unsupported audio formats surface as it.
    except (NemotronError, TranscriptionError, DialogueError) as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    finally:
        os.unlink(audio_path)

    lesson["history"].append({"student_input": transcription, "intent": result["intent"]})
    return {"transcription": transcription, "intent": result["intent"], "text": result["text"]}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
