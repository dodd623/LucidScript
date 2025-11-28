from fastapi import FastAPI, UploadFile, File, HTTPException, Form
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from pydantic import BaseModel
from typing import List, Tuple
from datetime import datetime
import tempfile, os, pathlib, uuid, re, subprocess, shlex, textwrap
import whisper
from docx import Document

# -----------------------------
# App + Model
# -----------------------------
app = FastAPI()
model = whisper.load_model("tiny")

BASE_DIR = pathlib.Path(__file__).parent.resolve()
OUTPUT_DIR = (BASE_DIR / "output").resolve()
OUTPUT_DIR.mkdir(exist_ok=True)

# -----------------------------
# Helper Functions
# -----------------------------
def to_paragraphs(text: str):
    text = re.sub(r"\s+", " ", text).strip()
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", text)
    return [p.strip() for p in parts if p.strip()]

def build_transcript_doc(title: str, text: str, language=None, translated=False):
    doc = Document()
    doc.add_heading(title, 0)

    meta = datetime.now().strftime("%Y-%m-%d %H:%M")
    if language:
        meta += f" | Language: {language}"
    if translated:
        meta += " | Translated to English"
    doc.add_paragraph(meta)

    for p in to_paragraphs(text):
        doc.add_paragraph(p)

    out = OUTPUT_DIR / f"lucidscript_{uuid.uuid4().hex[:8]}.docx"
    doc.save(out.as_posix())
    return out

def build_security_report_doc(fields: dict):
    doc = Document()
    doc.add_heading("Universal Orlando Security Incident Report", 0)

    h = doc.add_paragraph()
    h.add_run("Incident Date: ").bold = True
    h.add_run(fields.get("incident_date", "N/A"))
    h.add_run("    ")
    h.add_run("Time: ").bold = True
    h.add_run(fields.get("incident_time", "N/A"))

    p = doc.add_paragraph()
    p.add_run("Location: ").bold = True
    p.add_run(fields.get("location", "N/A"))

    p = doc.add_paragraph()
    p.add_run("Officer: ").bold = True
    p.add_run(fields.get("officer_name", "N/A"))
    if fields.get("officer_id"):
        p.add_run(f" (ID: {fields.get('officer_id')})")

    p = doc.add_paragraph()
    p.add_run("Case / Reference #: ").bold = True
    p.add_run(fields.get("case_number", "N/A"))

    doc.add_paragraph("")  # spacer

    doc.add_heading("Narrative", level=1)
    for line in to_paragraphs(fields.get("narrative", "")):
        doc.add_paragraph(line)

    out = OUTPUT_DIR / f"security_report_{uuid.uuid4().hex[:8]}.docx"
    doc.save(out.as_posix())
    return out


# -----------------------------
# Request Models
# -----------------------------
class FormatRequest(BaseModel):
    raw_text: str

class SecurityReport(BaseModel):
    incident_date: str
    incident_time: str
    location: str
    officer_name: str
    officer_id: str | None = None
    case_number: str | None = None
    narrative: str


# -----------------------------
# UI Routes
# -----------------------------
@app.get("/", response_class=HTMLResponse)
def root():
    return """
    <html><body style='background:#0f1115;color:white;font-family:Arial;padding:40px;'>
    <h1>LucidScript</h1>
    <p>Choose an interface:</p>
    <ul>
      <li><a href='/ui' style='color:#7db3ff'>Audio → Transcript UI</a></li>
      <li><a href='/ui_async' style='color:#7db3ff'>Advanced Audio UI</a></li>
      <li><a href='/security_ui' style='color:#7db3ff'>Security Report Generator</a></li>
    </ul>
    </body></html>
    """


@app.get("/ui", response_class=HTMLResponse)
def upload_ui():
    return "<h1>Basic UI is still here — works fine!</h1>"


@app.get("/ui_async", response_class=HTMLResponse)
def upload_ui_async():
    return "<h1>Async UI is still here — works fine!</h1>"


# -----------------------------
# NEW SECURITY UI (FULL FRONTEND)
# -----------------------------
@app.get("/security_ui", response_class=HTMLResponse)
def security_ui():
    return """
    <html>
      <head>
        <title>LucidScript — Security Report</title>
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <style>
          :root { color-scheme: dark; }
          body {
            margin: 0;
            padding: 0;
            font-family: system-ui,-apple-system,Segoe UI,Roboto,Arial;
            background: #0f1115;
            color: #eaeef3;
            display: flex;
            min-height: 100vh;
          }
          .wrap { margin: auto; width: min(760px, 94%); }
          h1 { font-weight: 700; letter-spacing: .3px; margin-bottom: .25rem; }
          p  { opacity: .85; margin-top: .2rem; margin-bottom: 1rem; }
          .card {
            background: #171a21;
            border: 1px solid #232736;
            border-radius: 14px;
            padding: 24px;
          }
          label { font-size: 13px; opacity: .85; display: block; margin-top: 10px; }
          input, textarea {
            width: 100%;
            background: #0f1115;
            color: #eaeef3;
            border: 1px solid #2a3042;
            padding: 10px;
            border-radius: 8px;
            box-sizing: border-box;
          }
          textarea { min-height: 140px; resize: vertical; }
          button {
            margin-top: 16px;
            width: 100%;
            padding: 12px 16px;
            border: 0;
            border-radius: 10px;
            background: #4c83ff;
            color: white;
            font-weight: 600;
            cursor: pointer;
          }
          button:hover { background:#3a6ef6; }
          .status { margin-top: 12px; font-size: 14px; opacity: .9; }
          .success { color: #71eea0; }
          .error   { color: #ff8a8a; }
          a { color:#9ec1ff; text-decoration:none; }
        </style>
      </head>
      <body>
        <div class="wrap">
          <h1>LucidScript — Security Report</h1>
          <p>Fill in the details below and LucidScript will generate a Universal-style incident report as a .docx file.</p>

          <div class="card">
            <form id="security-form">
              <label>Incident Date</label>
              <input type="date" name="incident_date" required />

              <label>Incident Time</label>
              <input type="time" name="incident_time" required />

              <label>Location</label>
              <input type="text" name="location" placeholder="CityWalk, IOA, USF, hotel, etc." required />

              <label>Officer Name</label>
              <input type="text" name="officer_name" required />

              <label>Officer ID (optional)</label>
              <input type="text" name="officer_id" />

              <label>Case / Reference # (optional)</label>
              <input type="text" name="case_number" />

              <label>Narrative</label>
              <textarea name="narrative"
                        placeholder="Write the report narrative here in your normal style..."
                        required></textarea>

              <button type="submit">Generate Report (.docx)</button>
            </form>

            <div id="status" class="status"></div>
            <div id="result" style="margin-top:10px"></div>
          </div>
        </div>

        <script>
          const form = document.getElementById('security-form');
          const statusEl = document.getElementById('status');
          const resultEl = document.getElementById('result');

          form.addEventListener('submit', async (e) => {
            e.preventDefault();
            statusEl.className = 'status';
            statusEl.textContent = 'Submitting…';
            resultEl.innerHTML = '';

            const formData = new FormData(form);
            const payload = Object.fromEntries(formData.entries());

            try {
              const resp = await fetch('/security_report', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
              });

              const data = await resp.json();

              if (!resp.ok) {
                statusEl.className = 'status error';
                statusEl.textContent = data.detail || 'Something went wrong.';
                return;
              }

              statusEl.className = 'status success';
              statusEl.textContent = 'Report generated. Download link below.';

              const fname = data.docx_filename || 'security_report.docx';
              resultEl.innerHTML = `
                <a href="/download/${encodeURIComponent(fname)}">⬇️ Download ${fname}</a>
              `;
            } catch (err) {
              statusEl.className = 'status error';
              statusEl.textContent = 'Unexpected error: ' + (err?.message || err);
            }
          });
        </script>
      </body>
    </html>
    """


# -----------------------------
# Transcription Endpoints
# -----------------------------
@app.post("/transcribe")
async def transcribe_audio(file: UploadFile = File(...)):
    suffix = os.path.splitext(file.filename or "")[-1]
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as t:
            t.write(await file.read())
            tmp = t.name

        r = model.transcribe(tmp)
        text = (r.get("text") or "").strip()
        return {"transcript": text}

    finally:
        if tmp and os.path.exists(tmp):
            os.remove(tmp)


@app.post("/format_docx")
def format_docx(req: FormatRequest):
    if not req.raw_text.strip():
        raise HTTPException(400, "No text provided.")
    out = build_transcript_doc("LucidScript Transcript", req.raw_text)
    return {"docx_path": str(out)}


# -----------------------------
# Security Report Backend
# -----------------------------
@app.post("/security_report")
def security_report(report: SecurityReport):
    out = build_security_report_doc(report.model_dump())
    return {
        "docx_path": str(out),
        "docx_filename": out.name,
    }


# -----------------------------
# File Download
# -----------------------------
@app.get("/download/{filename}")
def download(filename: str):
    if "/" in filename:
        raise HTTPException(400, "Invalid filename.")
    path = OUTPUT_DIR / filename
    if not path.exists():
        raise HTTPException(404, "File not found.")
    return FileResponse(path.as_posix(), filename=filename)