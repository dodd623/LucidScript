from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel
import tempfile, os, pathlib, uuid, re
import whisper
from docx import Document
from datetime import datetime
from fastapi import Form
from fastapi.responses import JSONResponse

# start the app
app = FastAPI()

# whisper model (tiny = fast for testing)
model = whisper.load_model("tiny")

BASE_DIR = pathlib.Path(__file__).parent.resolve()

# output folder for generated files
OUTPUT_DIR = (BASE_DIR / "output").resolve()
OUTPUT_DIR.mkdir(exist_ok=True)

UI_TEMPLATE_PATH = BASE_DIR / "frontend" / "ui.html"
try:
    UI_TEMPLATE = UI_TEMPLATE_PATH.read_text(encoding="utf-8")
except FileNotFoundError:
    UI_TEMPLATE = None

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
    text = re.sub(r"\s+", " ", text).strip()
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", text)
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

# new async ui for language/translate
@app.get("/ui_async", response_class=HTMLResponse)
def upload_ui_async():
    return """
    <html>
      <head>
        <title>LucidScript — Async</title>
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <style>
          :root { color-scheme: dark; }
          body { margin:0; padding:0; font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial;
                 background:#0f1115; color:#eaeef3; display:flex; min-height:100vh; }
          .wrap { margin:auto; width:min(760px, 94%); }
          h1 { font-weight:700; letter-spacing:.3px; margin-bottom:.25rem; }
          p { opacity:.85; margin-top:.2rem; margin-bottom:1rem; }
          .row { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
          .card { background:#171a21; border:1px solid #232736; border-radius:14px; padding:24px; }
          input[type=file], select {
            width:100%; background:#0f1115; color:#eaeef3; border:1px solid #2a3042;
            padding:12px; border-radius:10px;
          }
          label { font-size:12px; opacity:.8; }
          fieldset { border:1px solid #2a3042; border-radius:12px; padding:12px; }
          legend { opacity:.8; font-size:12px; padding:0 6px; }
          button { margin-top:14px; width:100%; padding:12px 16px; border:0; border-radius:10px;
                   background:#4c83ff; color:white; font-weight:600; cursor:pointer; }
          button:hover { background:#3a6ef6; }
          small { display:block; margin-top:10px; opacity:.65; }
          a { color:#9ec1ff; text-decoration:none; }
          .hint { margin-top:10px; font-size:12px; opacity:.8; }
          code { background:#0b0d12; padding:2px 6px; border-radius:6px; }
          .status { margin-top:12px; font-size:14px; opacity:.9; }
          .success { color:#71eea0; }
          .error { color:#ff8a8a; }
          .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
          .stack { display:flex; gap:12px; align-items:center; }
        </style>
      </head>
      <body>
        <div class="wrap">
          <h1>LucidScript</h1>
          <p>Upload audio → (optional) set language/translate → choose output style → download .docx — no page reload.</p>

          <div class="card">
            <form id="ls-form">
              <label>Audio file</label>
              <input id="file" type="file" name="file"
                     accept=".wav,.mp3,.m4a,.aac,.flac,.ogg,.webm,.mp4,audio/*,video/*" required />

              <div class="row" style="margin-top:12px">
                <div>
                  <label>Language (choose or Auto)</label>
                  <select id="language" name="language">
                    <option value="">Auto-detect</option>
                    <option value="en">English — en</option>
                    <option value="es">Spanish — es</option>
                    <option value="pt">Portuguese — pt</option>
                    <option value="zh">Mandarin Chinese — zh</option>
                    <option value="fr">French — fr</option>
                  </select>
                </div>

                <div class="stack">
                  <input type="checkbox" id="translate" name="translate" value="true" />
                  <label for="translate">Translate to English</label>
                </div>
              </div>

              <div class="row" style="margin-top:12px">
                <fieldset>
                  <legend>Output style</legend>
                  <div class="stack">
                    <input type="radio" id="style-standard" name="style" value="standard" checked />
                    <label for="style-standard">Standard (paragraph doc)</label>
                  </div>
                  <div class="stack" style="margin-top:6px">
                    <input type="radio" id="style-deposition" name="style" value="deposition" />
                    <label for="style-deposition">Deposition (Q/A with speaker labels)</label>
                  </div>
                </fieldset>

                <fieldset>
                  <legend>Speaker detection</legend>
                  <div class="stack">
                    <input type="checkbox" id="diarize" name="diarize" value="true" />
                    <label for="diarize">Detect speakers (beta)</label>
                  </div>
                  <small>Requires ffmpeg; optional HuggingFace token improves labeling.</small>
                </fieldset>
              </div>

              <button type="submit">Transcribe & Export</button>
            </form>

            <div id="status" class="status"></div>
            <div id="result" style="margin-top:10px"></div>

            <small>Prefer the API? See <a href="/docs">/docs</a>.</small>
            <div class="hint">
              Supported: <code>WAV</code>, <code>MP3</code>, <code>M4A</code>, <code>AAC</code>, <code>FLAC</code>, <code>OGG</code>, <code>WEBM</code>, <code>MP4</code>
            </div>
          </div>
        </div>

        <script>
          const form = document.getElementById('ls-form');
          const statusEl = document.getElementById('status');
          const resultEl = document.getElementById('result');

          form.addEventListener('submit', async (e) => {
            e.preventDefault();
            statusEl.className = 'status';
            resultEl.innerHTML = '';
            statusEl.textContent = 'Uploading…';

            const fd = new FormData(form);
            fd.set('translate', document.getElementById('translate').checked ? 'true' : 'false');
            fd.set('diarize', document.getElementById('diarize').checked ? 'true' : 'false');

            const style = (document.querySelector('input[name="style"]:checked') || {}).value || 'standard';
            const endpoint = style === 'deposition' ? '/export_docx_from_audio_v3' : '/export_docx_from_audio_v2';

            try {
              statusEl.textContent = 'Transcribing with Whisper…';
              const resp = await fetch(endpoint, { method: 'POST', body: fd });
              const data = await resp.json();

              if (!resp.ok) {
                statusEl.className = 'status error';
                statusEl.textContent = data.detail || 'Transcription failed.';
                return;
              }

              statusEl.className = 'status success';
              statusEl.textContent = 'Done. Document ready.';

              const lang = data.language || 'unknown';
              const dur = (data.duration_sec !== null && data.duration_sec !== undefined) ? data.duration_sec : '—';
              const fname = data.docx_filename;

              resultEl.innerHTML = `
                <div class="mono">Language: ${lang} | Duration: ${dur}s</div>
                <div style="margin-top:8px">
                  <a href="/download/${encodeURIComponent(fname)}">⬇️ Download ${fname}</a>
                </div>
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

# safe download route
@app.get("/download/{filename}")
def download_file(filename: str):
    if "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename.")
    file_path = OUTPUT_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found.")
    return FileResponse(file_path.as_posix(), filename=filename, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")

# language + translate
@app.post("/export_docx_from_audio_v2")
async def export_docx_from_audio_v2(file: UploadFile = File(...), language: str | None = Form(None), translate: str | None = Form(None)):
    suffix = os.path.splitext(file.filename or "")[-1]
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(await file.read())
            tmp_path = tmp.name
        kwargs = {}
        if language:
            kwargs["language"] = language
        if (translate or "").lower() == "true":
            kwargs["task"] = "translate"
        result = model.transcribe(tmp_path, **kwargs)
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
        return JSONResponse({
            "message": "Transcription and document export complete.",
            "docx_path": str(out),
            "docx_filename": out.name,
            "language": result.get("language", "unknown"),
            "duration_sec": round(float(result.get("duration", 0)), 2) if "duration" in result else None,
            "translated": ((translate or "").lower() == "true"),
        })
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

# deposition/interview-style export
from typing import List, Tuple
import subprocess, shlex, textwrap

HUGGINGFACE_TOKEN = os.getenv("HUGGINGFACE_TOKEN")
try:
    from pyannote.audio import Pipeline as PyannotePipeline  # type: ignore
    _PYANNOTE_OK = True
except Exception:
    _PYANNOTE_OK = False

def _time_fmt(t: float):
    t = max(0.0, float(t))
    m = int(t // 60)
    s = int(round(t - 60 * m))
    return f"{m:02d}:{s:02d}"

def _convert_to_wav(src: str):
    out = (OUTPUT_DIR / f"tmp_{uuid.uuid4().hex[:8]}.wav").as_posix()
    cmd = f'ffmpeg -y -i {shlex.quote(src)} -ac 1 -ar 16000 {shlex.quote(out)}'
    try:
        subprocess.run(cmd, shell=True, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return out
    except Exception:
        return src

def _diarize_segments_dep(wav_path: str) -> List[Tuple[float, float, str]]:
    if not (_PYANNOTE_OK and HUGGINGFACE_TOKEN):
        return []
    try:
        pipe = PyannotePipeline.from_pretrained("pyannote/speaker-diarization-3.1", use_auth_token=HUGGINGFACE_TOKEN)
        diar = pipe(wav_path)
        segs = []
        for turn, _, spk in diar.itertracks(yield_label=True):
            segs.append((float(turn.start), float(turn.end), str(spk)))
        segs.sort(key=lambda x: x[0])
        return segs
    except Exception:
        return []

def _assign_speakers(segments: List[dict], dia: List[Tuple[float, float, str]]):
    if not dia:
        return [{"speaker": "Speaker 1", "start": s.get("start", 0.0), "end": s.get("end", 0.0), "text": (s.get("text") or "").strip()} for s in segments]
    labeled = []
    for seg in segments:
        s = seg.get("start", 0.0)
        e = seg.get("end", 0.0)
        txt = (seg.get("text") or "").strip()
        best, overlap = "Speaker 1", 0.0
        for ds, de, spk in dia:
            ov = max(0.0, min(e, de) - max(s, ds))
            if ov > overlap:
                best, overlap = spk, ov
        labeled.append({"speaker": best, "start": s, "end": e, "text": txt})
    return labeled

def _make_deposition_doc(title: str, language: str, translated: bool, labeled: List[dict]):
    doc = Document()
    doc.add_heading(title, 0)
    meta = f"{datetime.now().strftime('%Y-%m-%d %H:%M')}  |  Language: {language or 'unknown'}"
    if translated:
        meta += "  |  Translated→English"
    doc.add_paragraph(meta)

    line_limit = 25
    current_line = 0
    for seg in labeled:
        header = f"{seg['speaker']}  [{_time_fmt(seg['start'])}–{_time_fmt(seg['end'])}]"
        p = doc.add_paragraph(header)
        p.runs[0].bold = True
        for line in seg["text"].splitlines() or [""]:
            wrapped = "\n".join(textwrap.wrap(line, width=80)) or ""
            for sub in (wrapped.split("\n") if wrapped else [""]):
                if current_line >= line_limit:
                    doc.add_page_break()
                    current_line = 0
                doc.add_paragraph(f"    {sub}")
                current_line += 1

    out = OUTPUT_DIR / f"lucidscript_{uuid.uuid4().hex[:8]}.docx"
    doc.save(out.as_posix())
    return out

@app.post("/export_docx_from_audio_v3")
async def export_docx_from_audio_v3(file: UploadFile = File(...), language: str | None = Form(None), translate: str | None = Form(None), diarize: str | None = Form(None)):
    suffix = os.path.splitext(file.filename or "")[-1]
    tmp_path = None
    wav16k = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(await file.read())
            tmp_path = tmp.name

        kwargs = {}
        if language:
            kwargs["language"] = language
        if (translate or "").lower() == "true":
            kwargs["task"] = "translate"

        result = model.transcribe(tmp_path, **kwargs)
        text = (result.get("text") or "").strip()
        if not text:
            raise HTTPException(status_code=400, detail="No speech detected or empty transcript.")

        segments = result.get("segments", [])
        do_diar = (diarize or "").lower() == "true"
        if do_diar:
            wav16k = _convert_to_wav(tmp_path)
            dia = _diarize_segments_dep(wav16k)
            labeled = _assign_speakers(segments, dia)
        else:
            labeled = _assign_speakers(segments, [])

        out = _make_deposition_doc("LucidScript Deposition Transcript",
                                   result.get("language", "unknown"),
                                   ((translate or "").lower() == "true"),
                                   labeled)

        return JSONResponse({
            "message": "Deposition transcript complete.",
            "docx_path": str(out),
            "docx_filename": out.name,
            "language": result.get("language", "unknown"),
            "duration_sec": round(float(result.get("duration", 0)), 2) if "duration" in result else None,
            "translated": ((translate or "").lower() == "true")
        })
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Transcription failed: {e}")
    finally:
        try:
            if wav16k and wav16k != tmp_path and os.path.exists(wav16k):
                os.remove(wav16k)
        except Exception:
            pass
        try:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
