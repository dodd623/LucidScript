from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import tempfile, os, pathlib, uuid, re
import whisper
from docx import Document
from datetime import datetime

# spin up the app
app = FastAPI()

# whisper model (tiny = fast for testing)
model = whisper.load_model("tiny")

# output folder for generated files
OUTPUT_DIR = pathlib.Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)

# quick ping
@app.get("/")
def home():
    return {"ok": True, "msg": "LucidScript backend is up"}

# super light UI so this feels like an app
@app.get("/ui", response_class=HTMLResponse)
def upload_ui():
    return """
    <html>
      <head>
        <title>LucidScript</title>
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <style>
          :root { color-scheme: dark; }
          body { margin:0; padding:0; font-family:system-ui, -apple-system, Segoe UI, Roboto, Arial;
                 background:#0f1115; color:#eaeef3; display:flex; min-height:100vh; }
          .wrap { margin:auto; width:min(640px, 92%); text-align:center; }
          h1 { font-weight:700; letter-spacing:.3px; margin-bottom:.2rem; }
          p { opacity:.8; margin-top:.2rem; margin-bottom:1.2rem; }
          .card { background:#171a21; border:1px solid #232736; border-radius:14px; padding:24px; }
          input[type=file] { width:100%; background:#0f1115; color:#eaeef3; border:1px dashed #2a3042;
                             padding:14px; border-radius:10px; }
          button { margin-top:14px; width:100%; padding:12px 16px; border:0; border-radius:10px;
                   background:#4c83ff; color:white; font-weight:600; cursor:pointer; }
          button:hover { background:#3a6ef6; }
          small { display:block; margin-top:10px; opacity:.65; }
          a { color:#9ec1ff; text-decoration:none; }
          .hint { margin-top:10px; font-size:12px; opacity:.8; }
          code { background:#0b0d12; padding:2px 6px; border-radius:6px; }
        </style>
      </head>
      <body>
        <div class="wrap">
          <h1>LucidScript</h1>
          <p>Upload audio → get a transcript → auto-format to a .docx.</p>
          <div class="card">
            <form action="/export_docx_from_audio" enctype="multipart/form-data" method="post">
              <label for="file">Select an audio file:</label><br/><br/>
              <input
                id="file"
                type="file"
                name="file"
                accept=".wav,.mp3,.m4a,.aac,.flac,.ogg,.webm,.mp4,audio/*,video/*"
                required
              />
              <div class="hint">
                Supported: <code>WAV</code>, <code>MP3</code>, <code>M4A</code>, <code>AAC</code>, <code>FLAC</code>, <code>OGG</code>, <code>WEBM</code>, <code>MP4</code>
              </div>
              <button type="submit">Transcribe & Export</button>
            </form>
            <small>Prefer the API? Try <a href="/docs">/docs</a>.</small>
          </div>
        </div>
      </body>
    </html>
    """

# basic payload for direct text → docx
class FormatRequest(BaseModel):
    raw_text: str

# tiny helper to break text into readable paragraphs
def to_paragraphs(text: str):
    text = re.sub(r"\\s+", " ", text).strip()
    parts = re.split(r"(?<=[.!?])\\s+(?=[A-Z0-9])", text)
    return [p.strip() for p in parts if p.strip()]

# audio → text
@app.post("/transcribe")
async def transcribe_audio(file: UploadFile = File(...)):
    suffix = os.path.splitext(file.filename or "")[-1]
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(await file.read())
            tmp_path = tmp.name

        result = model.transcribe(tmp_path)
        text = (result.get("text") or "").strip()
        return {"transcript": text}
    finally:
        # temp file cleanup (best effort)
        try:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass

# text → docx
@app.post("/format_docx")
def format_docx(req: FormatRequest):
    doc = Document()
    doc.add_heading("LucidScript Transcript", 0)
    doc.add_paragraph(datetime.now().strftime("%Y-%m-%d %H:%M"))

    for p in to_paragraphs(req.raw_text):
        doc.add_paragraph(p)

    out = OUTPUT_DIR / f"lucidscript_{uuid.uuid4().hex[:8]}.docx"
    doc.save(out.as_posix())
    return {"docx_path": str(out)}

# one-shot: audio → transcript → docx (nice for the UI form)
@app.post("/export_docx_from_audio")
async def export_docx_from_audio(file: UploadFile = File(...)):
    suffix = os.path.splitext(file.filename or "")[-1]
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(await file.read())
            tmp_path = tmp.name

        result = model.transcribe(tmp_path)
        text = (result.get("text") or "").strip()
        if not text:
            raise HTTPException(status_code=400, detail="No speech detected or empty transcript.")

        doc = Document()
        doc.add_heading("LucidScript Transcript", 0)
        doc.add_paragraph(datetime.now().strftime("%Y-%m-%d %H:%M"))
        for p in to_paragraphs(text):
            doc.add_paragraph(p)

        out = OUTPUT_DIR / f"lucidscript_{uuid.uuid4().hex[:8]}.docx"
        doc.save(out.as_posix())

        return {
            "message": "Transcription and document export complete.",
            "docx_path": str(out),
            "language": result.get("language", "unknown"),
            "duration_sec": round(float(result.get("duration", 0)), 2) if "duration" in result else None,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Transcription failed: {e}")
    finally:
        try:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
