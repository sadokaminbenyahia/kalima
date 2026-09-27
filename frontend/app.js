// Kalima frontend: upload a PDF, hear it part by part, ask questions by holding to talk.
"use strict";

const API_BASE = "http://localhost:8000";

const READY_MESSAGE = "Ready — press and hold the button to speak, or hold Space.";
// Recordings shorter than this are almost always an accidental tap.
const MIN_RECORDING_MS = 400;
// Upload can take minutes (one model call per page); refresh the status so it doesn't look frozen.
const UPLOAD_PROGRESS_INTERVAL_MS = 15000;

const state = {
  lessonId: null,
  parts: [],
  partIndex: 0,
  currentPart: null, // {title, text} of the part on screen, for "Read again"
  busy: false, // an /ask or /explain request is in flight
};

const el = {
  status: document.getElementById("status"),
  logo: document.getElementById("brand-logo"),
  partCounter: document.getElementById("part-counter"),
  uploadView: document.getElementById("upload-view"),
  fileInput: document.getElementById("file-input"),
  chooseFile: document.getElementById("choose-file"),
  lessonView: document.getElementById("lesson-view"),
  partTitle: document.getElementById("part-title"),
  partText: document.getElementById("part-text"),
  lessonComplete: document.getElementById("lesson-complete"),
  mic: document.getElementById("mic-button"),
  readAgain: document.getElementById("read-again"),
  nextPart: document.getElementById("next-part"),
  log: document.getElementById("log"),
};

// ---------- Shared helpers ----------

function setStatus(text) {
  el.status.textContent = text;
}

async function api(path, options) {
  let response;
  try {
    response = await fetch(API_BASE + path, options);
  } catch {
    throw new Error("Cannot reach the Kalima server. Is it running on port 8000?");
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    // FastAPI puts a string in `detail`, or a list of validation errors.
    const detail = typeof data.detail === "string" ? data.detail : `Server error ${response.status}`;
    throw new Error(detail);
  }
  return data;
}

// Hide the logo if it fails to load, rather than showing a broken-image icon.
function hideBrokenLogo() {
  el.logo.hidden = true;
}
el.logo.addEventListener("error", hideBrokenLogo);
if (el.logo.complete && el.logo.naturalWidth === 0) hideBrokenLogo();

// ---------- Upload state ----------

el.chooseFile.addEventListener("click", () => el.fileInput.click());
el.fileInput.addEventListener("change", () => handleUpload(el.fileInput.files[0]));

async function handleUpload(file) {
  if (!file) return;
  if (!file.name.toLowerCase().endsWith(".pdf")) {
    setStatus("Please choose a PDF file.");
    return;
  }

  el.chooseFile.disabled = true;
  setStatus("Reading your document… This can take a minute or two.");
  const startedAt = Date.now();
  const progressTimer = setInterval(() => {
    const seconds = Math.round((Date.now() - startedAt) / 1000);
    setStatus(`Still reading your document… (${seconds} seconds so far)`);
  }, UPLOAD_PROGRESS_INTERVAL_MS);

  const form = new FormData();
  form.append("file", file);
  try {
    const data = await api("/upload", { method: "POST", body: form });
    state.lessonId = data.lesson_id;
    state.parts = data.parts;
  } catch (error) {
    setStatus(`Could not read the document: ${error.message}`);
    return;
  } finally {
    clearInterval(progressTimer);
    el.chooseFile.disabled = false;
    el.fileInput.value = ""; // allow choosing the same file again
  }

  el.uploadView.hidden = true;
  el.lessonView.hidden = false;
  el.partCounter.hidden = false;
  await showPart(0);
}

// ---------- Lesson loop ----------

async function showPart(index) {
  let part;
  try {
    part = await api("/explain", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ lesson_id: state.lessonId, part_index: index }),
    });
  } catch (error) {
    setStatus(`Could not load the next part: ${error.message}`);
    return;
  }

  state.partIndex = index;
  state.currentPart = part;
  el.partCounter.textContent = `Part ${index + 1} of ${state.parts.length}`;
  el.partTitle.textContent = part.title;
  renderPartText(part.text);
  el.lessonComplete.hidden = true;
  el.partTitle.scrollIntoView({ block: "start" });
  readCurrentPart();
}

function readCurrentPart() {
  const part = state.currentPart;
  setStatus(`Reading part ${state.partIndex + 1} of ${state.parts.length}…`);
  speak(`${part.title}.\n${part.text}`, () => setStatus(READY_MESSAGE));
}

// Paragraphs as plain text; [Figure]/[Formula]/... lines are real content and shown as-is.
function renderPartText(text) {
  el.partText.replaceChildren(
    ...text.split(/\n\s*\n/).filter((p) => p.trim()).map((paragraph) => {
      const p = document.createElement("p");
      p.textContent = paragraph.trim();
      return p;
    }),
  );
}

async function advance() {
  if (state.partIndex >= state.parts.length - 1) {
    el.lessonComplete.hidden = false;
    setStatus("Lesson complete.");
    speak("Lesson complete. You can still ask questions about this part.");
    return;
  }
  await showPart(state.partIndex + 1);
}

// Fallback controls if voice input fails. "Next part" behaves exactly like a "continue" intent.
el.readAgain.addEventListener("click", () => {
  if (state.currentPart && !holding) readCurrentPart();
});
el.nextPart.addEventListener("click", async () => {
  if (state.busy || holding) return;
  setBusy(true);
  try {
    await advance();
  } finally {
    setBusy(false);
  }
});

function addLogEntry(speaker, text, className) {
  const item = document.createElement("li");
  item.className = className;
  const label = document.createElement("span");
  label.className = "speaker";
  label.textContent = `${speaker}: `;
  item.append(label, text);
  el.log.append(item);
  item.scrollIntoView({ block: "nearest" });
}

// ---------- Recording (push to talk) ----------

let mediaStream = null;
let recorder = null;
let holding = false; // true from press until release, even while waiting for mic permission
let recordingStartedAt = 0;

async function startRecording() {
  if (!state.lessonId || state.busy || holding) return;
  holding = true;
  stopSpeaking(); // don't record Kalima's own voice

  if (!mediaStream) {
    try {
      mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      holding = false;
      setStatus("Microphone access was blocked. Allow it in your browser settings, then try again.");
      return;
    }
    // Released while the permission prompt was open: nothing to record yet.
    if (!holding) {
      setStatus(READY_MESSAGE);
      return;
    }
  }

  const chunks = [];
  recorder = new MediaRecorder(mediaStream); // browser's default mimeType (WebM/Opus in Chrome/Firefox)
  recorder.addEventListener("dataavailable", (event) => {
    if (event.data.size > 0) chunks.push(event.data);
  });
  recorder.addEventListener("stop", () => {
    const duration = performance.now() - recordingStartedAt;
    const blob = new Blob(chunks, { type: recorder.mimeType });
    if (duration < MIN_RECORDING_MS || blob.size === 0) {
      setStatus("That was too short. Hold the button, or hold Space, while you speak.");
      return;
    }
    sendQuestion(blob);
  });
  recorder.start();
  recordingStartedAt = performance.now();
  el.mic.classList.add("is-recording");
  setStatus("Listening… release to send.");
}

function stopRecording() {
  if (!holding) return;
  holding = false;
  el.mic.classList.remove("is-recording");
  if (recorder && recorder.state === "recording") recorder.stop();
}

// The backend picks the audio format from the file extension, so name the blob to match.
function audioFilename(mimeType) {
  if (mimeType.includes("ogg")) return "question.ogg";
  if (mimeType.includes("mp4")) return "question.mp4";
  return "question.webm";
}

async function sendQuestion(blob) {
  setBusy(true);
  setStatus("Thinking…");

  const form = new FormData();
  form.append("lesson_id", state.lessonId);
  form.append("part_index", String(state.partIndex));
  form.append("audio", blob, audioFilename(blob.type));

  let reply;
  try {
    reply = await api("/ask", { method: "POST", body: form });
  } catch (error) {
    setStatus(`Sorry, something went wrong: ${error.message} Please try again.`);
    return;
  } finally {
    setBusy(false);
  }

  addLogEntry("You said", reply.transcription, "from-student");
  addLogEntry("Kalima", reply.text, "from-kalima");

  if (reply.intent === "continue") {
    await advance();
  } else {
    setStatus("Kalima is answering…");
    speak(reply.text, () => setStatus(READY_MESSAGE));
  }
}

function setBusy(busy) {
  state.busy = busy;
  el.mic.setAttribute("aria-disabled", String(busy));
  el.nextPart.disabled = busy;
}

// Mouse
el.mic.addEventListener("mousedown", (event) => {
  if (event.button === 0) startRecording();
});
el.mic.addEventListener("mouseup", stopRecording);
el.mic.addEventListener("mouseleave", stopRecording);

// Touch (preventDefault stops the emulated mouse events and the long-press menu)
el.mic.addEventListener("touchstart", (event) => {
  event.preventDefault();
  startRecording();
}, { passive: false });
el.mic.addEventListener("touchend", stopRecording);
el.mic.addEventListener("touchcancel", stopRecording);

// Keyboard: hold Space anywhere in the lesson, unless typing in a field or focused on another
// button (there Space keeps its normal meaning: press that button).
function keepsNativeSpace(target) {
  if (target === el.mic) return false;
  return target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT", "BUTTON"].includes(target.tagName);
}

function isPushToTalkKey(event) {
  return event.code === "Space" && !el.lessonView.hidden && !keepsNativeSpace(event.target);
}

document.addEventListener("keydown", (event) => {
  if (!isPushToTalkKey(event)) return;
  event.preventDefault(); // no page scroll, no button click
  if (!event.repeat) startRecording();
});
document.addEventListener("keyup", (event) => {
  if (!isPushToTalkKey(event)) return;
  event.preventDefault();
  stopRecording();
});
// If the window loses focus mid-hold, the keyup never arrives.
window.addEventListener("blur", stopRecording);

// ---------- Speech output ----------

// Each speak() call gets a token so callbacks from cancelled speech are ignored.
let speechToken = 0;

function speak(text, onEnd) {
  stopSpeaking();
  const token = speechToken;
  const chunks = splitForSpeech(text);
  if (!("speechSynthesis" in window) || chunks.length === 0) {
    if (onEnd) onEnd();
    return;
  }

  const lang = detectLang(text);
  chunks.forEach((chunk, i) => {
    const utterance = new SpeechSynthesisUtterance(chunk);
    utterance.lang = lang;
    if (i === chunks.length - 1 && onEnd) {
      const done = () => {
        if (token === speechToken) onEnd();
      };
      utterance.addEventListener("end", done);
      utterance.addEventListener("error", done);
    }
    window.speechSynthesis.speak(utterance);
  });
}

function stopSpeaking() {
  speechToken += 1;
  if ("speechSynthesis" in window) window.speechSynthesis.cancel();
}

// Chrome silently stops long utterances after ~15 seconds, so speak sentence-sized chunks.
const MAX_CHUNK_CHARS = 200;

function splitForSpeech(text) {
  const sentences = text
    .split(/\n+/)
    .flatMap((line) => line.match(/[^.!?…]+(?:[.!?…]+|$)/g) || [])
    .map((s) => s.trim())
    .filter(Boolean);

  const chunks = [];
  for (const sentence of sentences) {
    const last = chunks[chunks.length - 1];
    if (last && last.length + sentence.length + 1 <= MAX_CHUNK_CHARS) {
      chunks[chunks.length - 1] = `${last} ${sentence}`;
    } else {
      chunks.push(sentence);
    }
  }
  return chunks;
}

const FRENCH_WORDS = /\b(le|la|les|des|du|une|est|et|pour|dans|que|qui|sur|avec|pas|nous|vous|sont|ce|cette)\b/gi;
const ENGLISH_WORDS = /\b(the|and|is|are|of|to|in|that|with|for|this|you|it|on)\b/gi;
const FRENCH_ACCENTS = /[éèêëàâîïôùûüçœ]/i;

function detectLang(text) {
  const french = (text.match(FRENCH_WORDS) || []).length + (FRENCH_ACCENTS.test(text) ? 3 : 0);
  const english = (text.match(ENGLISH_WORDS) || []).length;
  return french > english ? "fr-FR" : "en-US";
}
