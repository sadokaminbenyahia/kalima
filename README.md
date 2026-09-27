# Kalima — AI Voice Tutor for Visually Impaired Students

Kalima is a voice-driven AI tutor that reads a course document **one part at a time** and lets the
student interrupt by voice to ask a question, ask for a simpler re-explanation, or move on.

Built for the **GOMYCODE x NVIDIA "Come Build with AI"** hackathon (Tunisia, September 2026).

## How it works

1. **Upload** a PDF or an image of a course page.
2. Kalima **extracts** the content (text, diagrams, formulas) and **splits** it into logical parts.
3. For each part:
   - Kalima **explains** it aloud.
   - The student holds the **push-to-talk** button (or `Space`) and speaks.
   - Kalima figures out what the student wants:
     - **question**: answers using the lesson content
     - **re-explain**: explains the same part again, more simply
     - **continue**: moves to the next part
     - **unclear**: asks the student to rephrase

## Tech stack

| Layer | Technology |
| --- | --- |
| AI model | NVIDIA `nemotron-3-nano-omni-30b-a3b-reasoning`: a single multimodal model for OCR, speech transcription, and dialogue |
| Backend | Python, FastAPI, PyMuPDF (renders each PDF page to an image) |
| Frontend | Plain HTML/CSS/JS, `MediaRecorder` for voice input, Web Speech API for speech output |

Accessibility: every status change is announced through an `aria-live` region, all controls work from
the keyboard, the layout uses high contrast, and the text uses the Atkinson Hyperlegible font.

## Project structure

```
backend/
  main.py                 FastAPI app: /upload, /explain, /ask
  models/nemotron_client.py   NVIDIA API wrapper
  pipeline/
    extract.py            PDF/image → text
    segment.py            text → ordered lesson parts
    transcribe.py         student audio → text
    dialogue.py           intent classification + answers
  requirements.txt
frontend/
  index.html  app.js  style.css
PROJECT.md                full build spec
```

## Getting started

### 1. Backend

```bash
cd backend
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS / Linux
pip install -r requirements.txt
```

Create `backend/.env` with your NVIDIA API key
(get one at <https://build.nvidia.com/nvidia/nemotron-3-nano-omni-30b-a3b-reasoning>):

```
NVIDIA_API_KEY=your_key_here
```

Run the server:

```bash
uvicorn main:app --reload --port 8000
```

You can test the API at <http://localhost:8000/docs>.

### 2. Frontend

Serve the `frontend/` folder with any static server, for example:

```bash
cd frontend
python -m http.server 5500
```

Open <http://localhost:5500> in Chrome or Edge, and allow microphone access when the browser asks.

## API

| Method | Endpoint | Body | Returns |
| --- | --- | --- | --- |
| POST | `/upload` | PDF or image file | `{lesson_id, parts}` |
| POST | `/explain` | `{lesson_id, part_index}` | explanation text for that part |
| POST | `/ask` | `lesson_id`, `part_index`, audio file | `{intent, text}` |

## Sample files

The repository root holds sample PDFs and audio clips (`test_*.wav`, `test_*.pdf`, …) that you can
use to try the full flow.

## Author

**Sadok Amin Ben Yahia**: [github.com/sadokaminbenyahia](https://github.com/sadokaminbenyahia)
