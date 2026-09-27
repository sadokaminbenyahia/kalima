# Kalima — AI Voice Tutor for Visually Impaired Students

Hackathon: GOMYCODE x NVIDIA "Come Build with AI"

This file is the build spec for Claude Code. It describes what to build, why, and the exact API to
integrate with. Read it fully before writing code.

## 1. What This Is

Kalima is an interactive, voice-driven AI tutor for visually impaired students. Instead of converting a
course document into one long static audio file, it reads a lesson **in segments** and lets the student
interrupt at any point — by voice — to ask a question, ask for a re-explanation, or move on to the next
part.

This is different from typical "accessibility conversion" tools (EduAccess AI, Verbit, Subly, etc.), which
turn pre-recorded lecture video into captions/audio-description as a one-shot, static output. Kalima:

- Targets **documents** (PDF, slides, photographed textbook pages) — not pre-recorded video — because
  that's the format most everyday coursework arrives in.
- Runs a **live back-and-forth dialogue**, not a converted file: the student can interrupt, question, and
  redirect the lesson, closer to a real tutoring session.
- Is built on a **single multimodal NVIDIA model** (image + audio + text in one API), not a stitched
  pipeline of separate OCR/ASR/TTS services.

## 2. Target User

A visually impaired student who has course material (PDF, slide deck, or a photo of a textbook/whiteboard)
and needs to actually understand it — including diagrams and formulas — not just have it read aloud once
from start to end with no way to ask questions.

## 3. Interaction Flow

```
1. Upload document
2. Segment into logical parts (ONE TIME, at upload — not during playback)
3. LOOP for each part:
   a. Explain current part (text-to-speech)
   b. Wait for student input (push-to-talk button — NOT open-mic/continuous listening)
   c. Student presses button, speaks → transcribe → classify intent:
      - "question"    → answer using this part's content (+ prior parts if needed) → back to (b)
      - "re-explain"  → reformulate the SAME part, simpler wording → speak it → back to (b)
      - "continue"    → advance to next part (back to loop start) or, if last part, go to step 4
      - unclear/off-topic → say so, offer to continue → back to (b)
4. Lesson complete
```

**Important implementation decisions already made — do not relitigate these without asking:**

- **Push-to-talk, not continuous listening.** Real-time interruption detection (knowing when the student
  is talking over the AI) is out of scope for the time available. Use an explicit button/key press to
  start/stop capturing the student's voice.
- **Segmentation happens once, at upload time**, not live during playback. The whole document is split
  into an ordered list of parts before the lesson loop starts.
- **State to track across the loop:** current part index, the full list of parts (so "re-explain" and
  cross-part questions work), and a simple conversation history for context.

## 4. Tech Stack

### Core model: `nemotron-3-nano-omni-30b-a3b-reasoning` (NVIDIA, confirmed Free Endpoint)

This ONE model handles the entire pipeline:

| Task | Input | Notes |
| --- | --- | --- |
| Document extraction (OCR, diagrams, formulas) | Image (jpeg/png) | PDFs must be rendered page-by-page to PNG first — the API does not accept raw PDF |
| Voice question transcription | Audio (wav/mp3, up to 1 hour) | |
| Intent classification & answering | Text | Use "instruct mode" (non-thinking) for fast, low-latency responses during the live demo; reserve "thinking mode" only if a question needs deeper reasoning |

- OpenAI-compatible API (use the `openai` Python SDK, pointed at NVIDIA's `base_url`).
- Get an API key from https://build.nvidia.com/nvidia/nemotron-3-nano-omni-30b-a3b-reasoning ("Get API Key").
- Example calls (image, audio, text) are on that model's page under "API Reference" — pull the exact
  request shape from there when wiring up each pipeline stage.
- For PDFs: render each page to PNG (e.g. with `pymupdf`/`fitz`), then send each page image through the
  same image-understanding call used for OCR.

### Output: Web Speech API (browser), NOT an NVIDIA model

`nemotron-3-nano-omni` only outputs text. For spoken output, use the browser's built-in
`SpeechSynthesis` API (`window.speechSynthesis`) — free, immediate, no API key, works in French and
English. This was a deliberate choice: NVIDIA's `magpie-tts-zeroshot` has a Free Endpoint but requires
"Apply for Access" (gated, not guaranteed same-day), so it was not relied on for the demo.

### Rejected alternatives (do not re-introduce without a reason)

- `nemotron-ocr-v2`, `parakeet-tdt-0.6b` (ASR), `chatterbox-multilingual-tts` — all "Downloadable" only on
  NVIDIA Build, **no Free Endpoint** — would require self-hosting on a GPU we don't have.
- `glm-5-3-flash` (Z.ai, hosted on NVIDIA Build) — text + image only, confirmed **no audio support** in its
  model card. Strong document/image reasoning with a much larger context window (1,048,576 tokens vs
  256k), so it's a documented fallback if a document is too large/complex for the primary model — not the
  default path.

## 5. Backend

Keep it a single small service — no need for multiple microservices today.

- **Framework: FastAPI** (Python) — fast to write, async-friendly for the audio/image calls, automatic
  `/docs` page useful for the team to test endpoints without a frontend.
- **Endpoints (minimum viable):**
  - `POST /upload` — accepts a PDF/image, runs extraction + segmentation, returns `{lesson_id, parts: [...]}`.
  - `POST /explain` — `{lesson_id, part_index}` → returns the text for that part (frontend sends this text to `speechSynthesis`).
  - `POST /ask` — `{lesson_id, part_index, audio}` → transcribes, classifies intent, returns
    `{intent: "question"|"re-explain"|"continue"|"unclear", text: "..."}`.
- **State:** an in-memory dict keyed by `lesson_id` is enough for a hackathon demo — no database needed.
- **CORS:** enable it wide open (`allow_origins=["*"]`) for the demo; note in the code that this needs
  tightening for anything beyond the hackathon.
- **Config:** load `NVIDIA_API_KEY` from a `.env` file (`python-dotenv`) — never hardcode it in source.

## 6. Frontend

- **Plain HTML/CSS/JS, no framework, no build step.** With this little time, a React/Vite setup costs more
  in tooling than it saves. One `index.html` + one `app.js` is faster to iterate on and just as demoable.
- **Accessibility is the actual point of this project, so it has to be real, not decorative:**
  - Every state change (part started, waiting for input, answer ready) announced via an
    `aria-live="polite"` region — a screen-reader user must be told what's happening without looking at
    the screen.
  - Push-to-talk bound to a large, easy-to-hit button AND a keyboard shortcut (e.g. hold `Space`) — never
    mouse-only.
  - High contrast, large hit targets, logical tab order — test with a screen reader (VoiceOver on
    Mac/iOS, NVDA on Windows, or the browser's own accessibility inspector) at least once before the demo.
- **Audio capture:** `MediaRecorder` API in the browser, sent to `/ask` as a file/blob.
- **Audio output:** `window.speechSynthesis.speak(new SpeechSynthesisUtterance(text))`; set `.lang` to
  `"fr-FR"` or `"en-US"` depending on the document's language.

## 7. Deployment

Given the time budget, **prioritize a rock-solid local demo over a public deployment.** The hackathon's
live demo round (country winners only) happens in person/on the shared call — a laptop running the app
locally is enough for that. Don't burn build time on infrastructure unless the core loop already works
end-to-end.

If a public link is genuinely needed for submission (check the exact submission form requirements — "every
submission link opens" may just mean your GitHub repo and demo video link, not a live app):

- **Frontend:** static file, deploy in minutes to **Vercel**, **Netlify**, or **GitHub Pages** (free, drag-and-drop or one CLI command).
- **Backend:** **Render** or **Railway** free tier — both deploy a FastAPI app from a GitHub repo with
  almost no config. Set `NVIDIA_API_KEY` as an environment variable in their dashboard, not in the repo.
- **Fastest option if time is very short:** run the backend locally and expose it with **ngrok** or
  **localtunnel** for a temporary public URL during the live demo window only.

## 8. Claude Code Setup (MCP & Skills)

Nothing special is required. This is a straightforward Python (FastAPI) + vanilla JS build — Claude Code's
built-in file, shell, and edit tools cover all of it: `pip install`/`npm` via the shell, editing files
directly, running the dev server.

- **No MCP servers needed** for the core build. The NVIDIA model is called over plain HTTPS (the `openai`
  SDK pointed at NVIDIA's endpoint) — that's a normal HTTP call, not something that needs an MCP
  integration.
- **Optional, only if time allows:** a browser-automation MCP (e.g. a Playwright-based one, if available
  in your Claude Code setup) can be useful for automatically clicking through the push-to-talk flow while
  debugging the frontend, instead of testing by hand every time. Not required to ship the project.
- **Do put the real `NVIDIA_API_KEY` only in a local `.env` file, and add `.env` to `.gitignore`** before
  the first commit — don't let Claude Code (or anyone) paste the key into a shared chat, a doc, or a public
  repo.

## 9. Suggested Project Structure

```
kalima/
├── backend/
│   ├── main.py              # FastAPI app: /upload, /explain, /ask
│   ├── pipeline/
│   │   ├── extract.py       # PDF→PNG, image understanding calls (OCR + diagram description)
│   │   ├── segment.py       # split extracted content into ordered lesson parts
│   │   ├── transcribe.py    # audio → text (student's spoken input)
│   │   └── dialogue.py      # intent classification + answering + re-explain, with context
│   ├── models/
│   │   └── nemotron_client.py  # thin wrapper around the NVIDIA API (OpenAI SDK client)
│   └── requirements.txt
├── frontend/
│   ├── index.html           # accessible UI: upload, push-to-talk button, lesson state, aria-live region
│   ├── app.js                # MediaRecorder for input, speechSynthesis for output, calls backend
│   └── style.css             # high-contrast, keyboard-navigable
├── .env                       # NVIDIA_API_KEY=... (gitignored)
└── .gitignore
```

## 10. Build Order (suggested)

1. `nemotron_client.py` — get one working call to the model (text-only "hello world") to confirm the API
   key and endpoint work.
2. `extract.py` — upload a test PDF, render to PNG, send one page through image understanding, confirm you
   get back readable text + a diagram description.
3. `segment.py` — take the full extracted text and produce a JSON list of ordered parts (a text-only call
   to the same model, prompted to output structured JSON).
4. `dialogue.py` — given a part's text + student question (text, for now), get an answer. Test this before
   wiring up audio.
5. `transcribe.py` — record a short test audio clip, send it through the model, confirm transcription
   works, THEN connect it to `dialogue.py`'s intent classification.
6. FastAPI endpoints in `main.py` wiring the above together.
7. Frontend — upload, the lesson loop, the push-to-talk button, `MediaRecorder`, `speechSynthesis`.
8. End-to-end test with the actual demo document (a PDF with a paragraph, a diagram, and a formula).
9. Only if time remains: deploy per section 7.

## 11. Demo Script (90 seconds, for judges)

1. Upload a course PDF containing a paragraph, a diagram, and a formula.
2. System reads the first part aloud, **including a spoken description of the diagram** (not just "image
   detected" — this is the moment meant to differentiate the project).
3. Press the talk button, ask a question about that part out loud.
4. System answers using the lesson content, by voice.
5. Ask to move on; system reads the next part.

## 12. Submission Notes

- **NVIDIA Brev:** not used. Entirely built on confirmed Free Endpoint models; no Brev credits requested.
- **Known limitation to disclose:** TTS output uses the Web Speech API, not an NVIDIA model — a deliberate
  reliability choice over `magpie-tts-zeroshot`'s gated access.
- **Responsible AI:** the tutor must answer only from the uploaded lesson content, and say clearly when a
  question falls outside it rather than guessing.

## 13. Team Roles

| Role | Responsibility |
| --- | --- |
| Document pipeline (1-2 people) | `extract.py`, `segment.py` |
| Voice interaction (1 person) | `transcribe.py`, push-to-talk frontend wiring, `MediaRecorder` |
| Dialogue logic (1 person) | `dialogue.py` — intent classification, answering, re-explain, context |
| Interface & demo (1 person) | Accessible frontend, `speechSynthesis` integration, demo video, project card |