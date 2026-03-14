from fastapi import FastAPI, UploadFile, File, HTTPException, Form
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from pydantic import BaseModel
import tempfile, os, pathlib, uuid, re, subprocess, shlex, textwrap, html
from typing import List, Tuple
import whisper
import easyocr
from deep_translator import GoogleTranslator
from docx import Document
from datetime import datetime

app = FastAPI()

model_name = os.getenv("WHISPER_MODEL", "tiny").strip().lower()
allowed_models = {"tiny", "base", "small", "medium", "large"}
if model_name not in allowed_models:
    model_name = "tiny"

model = whisper.load_model(model_name)

ocr_reader = None
ocr_reader_ch = None
ocr_reader_ja = None

BASE_DIR = pathlib.Path(__file__).parent.resolve()
OUTPUT_DIR = (BASE_DIR / "output").resolve()
OUTPUT_DIR.mkdir(exist_ok=True)

TEMPLATE_DIR = (BASE_DIR / "templates").resolve()
WITNESS_TEMPLATE_PATH = TEMPLATE_DIR / "witness_statement_template.docx"

UI_TEMPLATE_PATH = BASE_DIR / "frontend" / "ui.html"
try:
    UI_TEMPLATE = UI_TEMPLATE_PATH.read_text(encoding="utf-8")
except FileNotFoundError:
    UI_TEMPLATE = None


def get_ocr_readers():
    global ocr_reader, ocr_reader_ch, ocr_reader_ja

    if ocr_reader is None:
        ocr_reader = easyocr.Reader(['en', 'es', 'fr', 'de', 'pt', 'it', 'nl'])

    if ocr_reader_ch is None:
        ocr_reader_ch = easyocr.Reader(['ch_sim', 'en'])

    if ocr_reader_ja is None:
        ocr_reader_ja = easyocr.Reader(['ja', 'en'])

    return ocr_reader, ocr_reader_ch, ocr_reader_ja


def landing_page_html() -> str:
    return """
    <html>
      <head>
        <title>LucidScript</title>
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <style>
          :root { color-scheme: dark; }
          body {
            margin:0; padding:0;
            font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial;
            background:#0f1115; color:#eaeef3;
            display:flex; min-height:100vh;
          }
          .wrap { margin:auto; width:min(640px, 92%); text-align:center; }
          h1 { font-weight:700; margin-bottom:.25rem; }
          p { opacity:.85; margin-top:.2rem; margin-bottom:1rem; }
          a.button {
            display:inline-block;
            margin-top:10px;
            padding:10px 18px;
            border-radius:10px;
            background:#4c83ff;
            color:white;
            font-weight:600;
            text-decoration:none;
          }
          a.button:hover { background:#3a6ef6; }
          .hint { margin-top:12px; font-size:12px; opacity:.75; }
          code { background:#0b0d12; padding:2px 6px; border-radius:6px; }
        </style>
      </head>
      <body>
        <div class="wrap">
          <h1>LucidScript</h1>
          <p>Upload audio, text, or images, then download a formatted Word document.</p>

          <a href="/ui_async" class="button">Open LucidScript UI</a>

          <div class="hint">
            • This page is the entry point if you don't go straight to '/ui_async'.<br/>
            • Developers can view the API docs at <code>/docs</code>.<br/>
            • Direct download links look like <code>/download/&lt;filename.docx&gt;</code>.<br/>
            • This is the working LucidScript build.<br/>
          </div>
        </div>
      </body>
    </html>
    """


@app.get("/", response_class=HTMLResponse)
async def root():
    return landing_page_html()


@app.get("/health")
async def health_check():
    return {"status": "ok", "whisper_model": model_name}


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
            <small>Prefer the API? Try <a href="/docs">/docs</a> or the async UI at <a href="/ui_async">/ui_async</a>.</small>
          </div>
        </div>
      </body>
    </html>
    """


class FormatRequest(BaseModel):
    raw_text: str


def to_paragraphs(text: str):
    text = re.sub(r"\s+", " ", text).strip()
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", text)
    return [p.strip() for p in parts if p.strip()]


def build_transcript_doc(
    title: str,
    text: str,
    language: str | None = None,
    translated: bool = False,
):
    doc = Document()
    doc.add_heading(title, 0)

    meta = datetime.now().strftime("%Y-%m-%d %H:%M")
    if language:
        meta += f"  |  Language: {language}"
    if translated:
        meta += "  |  Translated to English"

    doc.add_paragraph(meta)

    for p in to_paragraphs(text):
        doc.add_paragraph(p)

    out = OUTPUT_DIR / f"lucidscript_{uuid.uuid4().hex[:8]}.docx"
    doc.save(out.as_posix())
    return out


def build_security_report_doc(text: str):
    doc = Document()
    doc.add_heading("Security Report", 0)
    doc.add_paragraph(datetime.now().strftime("%Y-%m-%d %H:%M"))

    for block in text.splitlines():
        cleaned = block.strip()
        if cleaned:
            doc.add_paragraph(cleaned)
        else:
            doc.add_paragraph("")

    out = OUTPUT_DIR / f"text_transcript_{uuid.uuid4().hex[:8]}.docx"
    doc.save(out.as_posix())
    return out


def replace_placeholders_in_paragraph(paragraph, replacements: dict):
    full_text = "".join(run.text for run in paragraph.runs)
    if not full_text:
        return

    updated_text = full_text
    for key, value in replacements.items():
        updated_text = updated_text.replace(key, value)

    if updated_text != full_text:
        if paragraph.runs:
            paragraph.runs[0].text = updated_text
            for run in paragraph.runs[1:]:
                run.text = ""
        else:
            paragraph.text = updated_text


def replace_placeholders_in_doc(doc: Document, replacements: dict):
    for paragraph in doc.paragraphs:
        replace_placeholders_in_paragraph(paragraph, replacements)

    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    replace_placeholders_in_paragraph(paragraph, replacements)


def build_witness_statement_doc(
    witness_name: str,
    occupation: str,
    statement_body: str,
    age_text: str = "Over 18",
    date_text: str | None = None,
):
    if not WITNESS_TEMPLATE_PATH.exists():
        raise HTTPException(
            status_code=500,
            detail="Witness statement template file was not found in the templates folder.",
        )

    doc = Document(WITNESS_TEMPLATE_PATH.as_posix())

    replacements = {
        "{{WITNESS_NAME}}": witness_name.strip(),
        "{{OCCUPATION}}": occupation.strip(),
        "{{STATEMENT_BODY}}": statement_body.strip(),
        "{{DATE}}": (date_text or datetime.now().strftime("%m/%d/%Y")).strip(),
        "{{AGE}}": age_text.strip(),
    }

    replace_placeholders_in_doc(doc, replacements)

    out = OUTPUT_DIR / f"witness_statement_{uuid.uuid4().hex[:8]}.docx"
    doc.save(out.as_posix())
    return out


def extract_text_from_image(image_path: str) -> str:
    local_ocr_reader, local_ocr_reader_ch, local_ocr_reader_ja = get_ocr_readers()

    try:
        results = local_ocr_reader.readtext(image_path, detail=0, paragraph=True)
        text = "\n".join([line.strip() for line in results if line and line.strip()]).strip()
        if text:
            return text
    except Exception:
        pass

    try:
        results_ch = local_ocr_reader_ch.readtext(image_path, detail=0, paragraph=True)
        text_ch = "\n".join([line.strip() for line in results_ch if line and line.strip()]).strip()
        if text_ch:
            return text_ch
    except Exception:
        pass

    try:
        results_ja = local_ocr_reader_ja.readtext(image_path, detail=0, paragraph=True)
        text_ja = "\n".join([line.strip() for line in results_ja if line and line.strip()]).strip()
        if text_ja:
            return text_ja
    except Exception:
        pass

    return ""


def translate_text_to_english(text: str) -> str:
    if not text.strip():
        return text
    try:
        return GoogleTranslator(source="auto", target="en").translate(text)
    except Exception:
        return text


@app.post("/transcribe")
async def transcribe_audio(file: UploadFile = File(...)):
    suffix = os.path.splitext(file.filename or "")[-1]
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(await file.read())
            tmp_path = tmp.name
        result = model.transcribe(tmp_path)
        text = (result.get("text") or "").strip()
        return {"transcript": text}
    except Exception:
        raise HTTPException(
            status_code=500,
            detail="Something went wrong while processing the audio. Please try again with a different file.",
        )
    finally:
        try:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass


@app.post("/format_docx")
def format_docx(req: FormatRequest):
    if not req.raw_text.strip():
        raise HTTPException(
            status_code=400,
            detail="No text was provided to format.",
        )
    out = build_transcript_doc("LucidScript Transcript", req.raw_text)
    return {"docx_path": str(out)}


@app.post("/export_security_report")
async def export_security_report(report_text: str = Form(...)):
    if not report_text.strip():
        raise HTTPException(
            status_code=400,
            detail="No report text was provided.",
        )

    out = build_security_report_doc(report_text)

    return JSONResponse(
        {
            "message": "Text transcript formatted successfully.",
            "docx_path": str(out),
            "docx_filename": out.name,
        }
    )


@app.post("/export_security_report_from_image")
async def export_security_report_from_image(
    image_file: UploadFile = File(...),
    translate_to_english: str | None = Form(None),
):
    suffix = os.path.splitext(image_file.filename or "")[-1].lower()
    allowed = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}

    if suffix not in allowed:
        raise HTTPException(
            status_code=400,
            detail="Unsupported image format. Use PNG, JPG, JPEG, WEBP, or BMP.",
        )

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(await image_file.read())
            tmp_path = tmp.name

        extracted_text = extract_text_from_image(tmp_path)

        if not extracted_text:
            raise HTTPException(
                status_code=400,
                detail="No readable text was found in the uploaded image.",
            )

        translated_flag = (translate_to_english or "").lower() == "true"
        final_text = translate_text_to_english(extracted_text) if translated_flag else extracted_text

        out = build_security_report_doc(final_text)

        return JSONResponse(
            {
                "message": "Text transcript generated from image successfully.",
                "docx_path": str(out),
                "docx_filename": out.name,
                "extracted_text": extracted_text,
                "translated_text": final_text,
                "translated": translated_flag,
            }
        )
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=500,
            detail="Something went wrong while reading the image. Please try a clearer image.",
        )
    finally:
        try:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass


@app.post("/export_witness_statement")
async def export_witness_statement(
    witness_name: str = Form(...),
    occupation: str = Form(...),
    statement_body: str = Form(...),
    age_text: str = Form("Over 18"),
):
    if not witness_name.strip():
        raise HTTPException(status_code=400, detail="Witness name is required.")
    if not occupation.strip():
        raise HTTPException(status_code=400, detail="Occupation is required.")
    if not statement_body.strip():
        raise HTTPException(status_code=400, detail="Statement body is required.")

    out = build_witness_statement_doc(
        witness_name=witness_name,
        occupation=occupation,
        statement_body=statement_body,
        age_text=age_text,
    )

    return JSONResponse(
        {
            "message": "Witness statement generated successfully.",
            "docx_path": str(out),
            "docx_filename": out.name,
        }
    )


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
            raise HTTPException(
                status_code=400,
                detail="No speech was detected in this file. Try a different recording.",
            )

        language = result.get("language", "unknown")
        duration = round(float(result.get("duration", 0)), 2) if "duration" in result else None

        out = build_transcript_doc("LucidScript Transcript", text, language=language)

        return {
            "message": "Transcription finished. Word doc ready to download.",
            "docx_path": str(out),
            "language": language,
            "duration_sec": duration,
        }
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=500,
            detail="Something went wrong while processing the audio. Please try again with a different file.",
        )
    finally:
        try:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass


@app.get("/ui_async", response_class=HTMLResponse)
def upload_ui_async():
    return """
    <html>
      <head>
        <title>LucidScript — Async</title>
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <style>
          :root { color-scheme: dark; }
          body {
            margin:0; padding:0;
            font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial;
            background:#0f1115; color:#eaeef3;
            display:flex; min-height:100vh;
          }
          .wrap {
            margin:auto;
            width:min(900px, 94%);
            padding:32px 0;
          }
          h1 {
            font-weight:700;
            letter-spacing:.3px;
            margin-bottom:.25rem;
          }
          h2 {
            margin-top:0;
            margin-bottom:.5rem;
          }
          p {
            opacity:.85;
            margin-top:.2rem;
            margin-bottom:1rem;
          }
          .card {
            background:#171a21;
            border:1px solid #232736;
            border-radius:14px;
            padding:24px;
            margin-bottom:18px;
          }
          .row {
            display:grid;
            grid-template-columns:1fr 1fr;
            gap:12px;
          }
          input[type=file], input[type=text], select, textarea {
            width:100%;
            background:#0f1115;
            color:#eaeef3;
            border:1px solid #2a3042;
            padding:12px;
            border-radius:10px;
            box-sizing:border-box;
          }
          textarea {
            min-height:240px;
            resize:vertical;
            font-family:inherit;
          }
          label {
            font-size:12px;
            opacity:.8;
            display:block;
            margin-bottom:6px;
          }
          fieldset {
            border:1px solid #2a3042;
            border-radius:12px;
            padding:12px;
          }
          legend {
            opacity:.8;
            font-size:12px;
            padding:0 6px;
          }
          button {
            margin-top:14px;
            width:100%;
            padding:12px 16px;
            border:0;
            border-radius:10px;
            background:#4c83ff;
            color:white;
            font-weight:600;
            cursor:pointer;
          }
          button:hover {
            background:#3a6ef6;
          }
          small {
            display:block;
            margin-top:10px;
            opacity:.65;
          }
          a {
            color:#9ec1ff;
            text-decoration:none;
          }
          .hint {
            margin-top:10px;
            font-size:12px;
            opacity:.8;
          }
          code {
            background:#0b0d12;
            padding:2px 6px;
            border-radius:6px;
          }
          .status {
            margin-top:12px;
            font-size:14px;
            opacity:.9;
          }
          .success { color:#71eea0; }
          .error { color:#ff8a8a; }
          .mono {
            font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
          }
          .stack {
            display:flex;
            gap:12px;
            align-items:center;
          }
          .hidden {
            display:none;
          }
          .mode-row {
            margin-bottom:18px;
          }
          .result-box {
            margin-top:16px;
            padding-top:6px;
          }
          .two-up {
            display:grid;
            grid-template-columns:1fr 1fr;
            gap:12px;
            margin-top:12px;
          }
          @media (max-width: 700px) {
            .row { grid-template-columns:1fr; }
            .two-up { grid-template-columns:1fr; }
          }
        </style>
      </head>
      <body>
        <div class="wrap">
          <h1>LucidScript</h1>
          <p>Choose a mode, then process audio, pasted text, image text, or witness statements into a formatted .docx.</p>

          <div class="card">
            <div class="mode-row">
              <label for="mode">Mode</label>
              <select id="mode">
                <option value="audio">Audio Transcription</option>
                <option value="text">Text Input</option>
                <option value="image">Image Upload</option>
                <option value="witness">Witness Statement</option>
              </select>
            </div>

            <div id="mode-audio">
              <h2>Audio Transcription</h2>
              <p>Upload audio → optional language/translate → choose output style → download .docx.</p>

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

                  <div class="stack" style="margin-top:24px">
                    <input type="checkbox" id="translate" name="translate" value="true" />
                    <label for="translate" style="margin:0;">Translate to English</label>
                  </div>
                </div>

                <div class="row" style="margin-top:12px">
                  <fieldset>
                    <legend>Output style</legend>
                    <div class="stack">
                      <input type="radio" id="style-standard" name="style" value="standard" checked />
                      <label for="style-standard" style="margin:0;">Standard (paragraph doc)</label>
                    </div>
                    <div class="stack" style="margin-top:6px">
                      <input type="radio" id="style-deposition" name="style" value="deposition" />
                      <label for="style-deposition" style="margin:0;">Deposition (Q/A with speaker labels)</label>
                    </div>
                  </fieldset>

                  <fieldset>
                    <legend>Speaker detection</legend>
                    <div class="stack">
                      <input type="checkbox" id="diarize" name="diarize" value="true" />
                      <label for="diarize" style="margin:0;">Detect speakers (beta)</label>
                    </div>
                    <small>Requires ffmpeg; optional HuggingFace token improves labeling.</small>
                  </fieldset>
                </div>

                <button type="submit">Transcribe & Export</button>
              </form>

              <div class="hint">
                Supported: <code>WAV</code>, <code>MP3</code>, <code>M4A</code>, <code>AAC</code>, <code>FLAC</code>, <code>OGG</code>, <code>WEBM</code>, <code>MP4</code>
              </div>
            </div>

            <div id="mode-text" class="hidden">
              <h2>Text Input</h2>
              <p>Enter text and export it as your chosen format.</p>

              <form id="security-form">
                <label for="report_text">Report text</label>
                <textarea id="report_text" name="report_text" placeholder="Type or paste your report here..." required></textarea>
                <button type="submit">Generate DOCX</button>
              </form>
            </div>

            <div id="mode-image" class="hidden">
              <h2>Image Upload</h2>
              <p>Upload an image, extract multilingual text, optionally translate it to English, and export a .docx.</p>

              <form id="security-image-form">
                <label for="image_file">Image file</label>
                <input
                  id="image_file"
                  type="file"
                  name="image_file"
                  accept=".png,.jpg,.jpeg,.webp,.bmp,image/*"
                  required
                />

                <div class="stack" style="margin-top:12px">
                  <input type="checkbox" id="translate_image_text" name="translate_to_english" value="true" />
                  <label for="translate_image_text" style="margin:0;">Translate extracted text to English</label>
                </div>

                <button type="submit">Extract & Export</button>
              </form>

              <div class="hint">
                Supported: <code>PNG</code>, <code>JPG</code>, <code>JPEG</code>, <code>WEBP</code>, <code>BMP</code>
              </div>
            </div>

            <div id="mode-witness" class="hidden">
              <h2>Witness Statement</h2>
              <p>Fill in the witness details and statement body, then export using your witness statement template.</p>

              <form id="witness-form">
                <div style="margin-top:12px">
                  <label for="witness_name">Witness name</label>
                  <input id="witness_name" type="text" name="witness_name" placeholder="Enter witness name" required />
                </div>

                <div style="margin-top:12px">
                  <label for="statement_body">Statement body</label>
                  <textarea id="statement_body" name="statement_body" placeholder="Type or paste the witness statement body here..." required></textarea>
                </div>

                <button type="submit">Generate Witness Statement</button>
              </form>
            </div>

            <div id="shared-status" class="status result-box"></div>
            <div id="shared-result" class="result-box"></div>

            <small>Prefer the API? See <a href="/docs">/docs</a>.</small>
          </div>
        </div>

        <script>
          const modeSelect = document.getElementById('mode');
          const audioPanel = document.getElementById('mode-audio');
          const textPanel = document.getElementById('mode-text');
          const imagePanel = document.getElementById('mode-image');
          const witnessPanel = document.getElementById('mode-witness');

          const sharedStatusEl = document.getElementById('shared-status');
          const sharedResultEl = document.getElementById('shared-result');

          function setMode(mode) {
            audioPanel.classList.add('hidden');
            textPanel.classList.add('hidden');
            imagePanel.classList.add('hidden');
            witnessPanel.classList.add('hidden');

            if (mode === 'audio') {
              audioPanel.classList.remove('hidden');
            } else if (mode === 'text') {
              textPanel.classList.remove('hidden');
            } else if (mode === 'image') {
              imagePanel.classList.remove('hidden');
            } else if (mode === 'witness') {
              witnessPanel.classList.remove('hidden');
            }

            sharedStatusEl.className = 'status result-box';
            sharedStatusEl.textContent = '';
            sharedResultEl.innerHTML = '';
          }

          modeSelect.addEventListener('change', (e) => {
            setMode(e.target.value);
          });

          function escapeHtml(value) {
            return String(value)
              .replace(/&/g, '&amp;')
              .replace(/</g, '&lt;')
              .replace(/>/g, '&gt;')
              .replace(/"/g, '&quot;')
              .replace(/'/g, '&#039;');
          }

          function showError(message) {
            sharedStatusEl.className = 'status error result-box';
            sharedStatusEl.textContent = message;
          }

          function showSuccess(message) {
            sharedStatusEl.className = 'status success result-box';
            sharedStatusEl.textContent = message;
          }

          const audioForm = document.getElementById('ls-form');
          audioForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            sharedStatusEl.className = 'status result-box';
            sharedResultEl.innerHTML = '';
            sharedStatusEl.textContent = 'Uploading audio…';

            const fd = new FormData(audioForm);
            fd.set('translate', document.getElementById('translate').checked ? 'true' : 'false');
            fd.set('diarize', document.getElementById('diarize').checked ? 'true' : 'false');

            const style = (document.querySelector('input[name="style"]:checked') || {}).value || 'standard';
            const endpoint = style === 'deposition' ? '/export_docx_from_audio_v3' : '/export_docx_from_audio_v2';

            try {
              sharedStatusEl.textContent = 'Transcribing with Whisper…';
              const resp = await fetch(endpoint, { method: 'POST', body: fd });
              const data = await resp.json();

              if (!resp.ok) {
                showError(data.detail || 'Transcription failed.');
                return;
              }

              showSuccess('Done – .docx is ready below.');

              const lang = data.language || 'unknown';
              const dur = (data.duration_sec !== null && data.duration_sec !== undefined) ? data.duration_sec : '—';
              const fname = data.docx_filename;

              sharedResultEl.innerHTML = `
                <div class="mono">Language: ${escapeHtml(lang)} | Duration: ${escapeHtml(dur)}s</div>
                <div style="margin-top:8px">
                  <a href="/download/${encodeURIComponent(fname)}">⬇️ Download ${escapeHtml(fname)}</a>
                </div>
              `;
            } catch (err) {
              showError('Unexpected error: ' + (err?.message || err));
            }
          });

          const textForm = document.getElementById('security-form');
          textForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            sharedStatusEl.className = 'status result-box';
            sharedResultEl.innerHTML = '';
            sharedStatusEl.textContent = 'Formatting report…';

            const fd = new FormData(textForm);

            try {
              const resp = await fetch('/export_security_report', { method: 'POST', body: fd });
              const data = await resp.json();

              if (!resp.ok) {
                showError(data.detail || 'Report formatting failed.');
                return;
              }

              showSuccess('Done – .docx is ready below.');

              const fname = data.docx_filename;

              sharedResultEl.innerHTML = `
                <div style="margin-top:8px">
                  <a href="/download/${encodeURIComponent(fname)}">⬇️ Download ${escapeHtml(fname)}</a>
                </div>
              `;
            } catch (err) {
              showError('Unexpected error: ' + (err?.message || err));
            }
          });

          const imageForm = document.getElementById('security-image-form');
          imageForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            sharedStatusEl.className = 'status result-box';
            sharedResultEl.innerHTML = '';
            sharedStatusEl.textContent = 'Reading image…';

            const fd = new FormData(imageForm);
            fd.set(
              'translate_to_english',
              document.getElementById('translate_image_text').checked ? 'true' : 'false'
            );

            try {
              const resp = await fetch('/export_security_report_from_image', {
                method: 'POST',
                body: fd
              });
              const data = await resp.json();

              if (!resp.ok) {
                showError(data.detail || 'Image OCR failed.');
                return;
              }

              showSuccess('Done – .docx is ready below.');

              const fname = data.docx_filename;
              const previewText = data.translated_text || data.extracted_text || '';

              sharedResultEl.innerHTML = `
                <div style="margin-top:8px">
                  <a href="/download/${encodeURIComponent(fname)}">⬇️ Download ${escapeHtml(fname)}</a>
                </div>
                <div class="hint" style="margin-top:12px;">Preview:</div>
                <div class="mono" style="white-space:pre-wrap; margin-top:6px;">${escapeHtml(previewText)}</div>
              `;
            } catch (err) {
              showError('Unexpected error: ' + (err?.message || err));
            }
          });

          const witnessForm = document.getElementById('witness-form');
          witnessForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            sharedStatusEl.className = 'status result-box';
            sharedResultEl.innerHTML = '';
            sharedStatusEl.textContent = 'Generating witness statement…';

            const fd = new FormData(witnessForm);

            try {
              const resp = await fetch('/export_witness_statement', {
                method: 'POST',
                body: fd
              });
              const data = await resp.json();

              if (!resp.ok) {
                showError(data.detail || 'Witness statement generation failed.');
                return;
              }

              showSuccess('Done – witness statement .docx is ready below.');

              const fname = data.docx_filename;

              sharedResultEl.innerHTML = `
                <div style="margin-top:8px">
                  <a href="/download/${encodeURIComponent(fname)}">⬇️ Download ${escapeHtml(fname)}</a>
                </div>
              `;
            } catch (err) {
              showError('Unexpected error: ' + (err?.message || err));
            }
          });

          setMode('audio');
        </script>
      </body>
    </html>
    """


@app.get("/download/{filename}")
def download_file(filename: str):
    if "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename.")
    file_path = OUTPUT_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found.")
    return FileResponse(
        file_path.as_posix(),
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


@app.post("/export_docx_from_audio_v2")
async def export_docx_from_audio_v2(
    file: UploadFile = File(...),
    language: str | None = Form(None),
    translate: str | None = Form(None),
):
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
            raise HTTPException(
                status_code=400,
                detail="No speech was detected in this file. Try a different recording.",
            )

        lang = result.get("language", "unknown")
        duration = round(float(result.get("duration", 0)), 2) if "duration" in result else None
        translated_flag = (translate or "").lower() == "true"

        out = build_transcript_doc(
            "LucidScript Transcript",
            text,
            language=lang,
            translated=translated_flag,
        )

        return JSONResponse(
            {
                "message": "Transcription finished. Word doc ready to download.",
                "docx_path": str(out),
                "docx_filename": out.name,
                "language": lang,
                "duration_sec": duration,
                "translated": translated_flag,
            }
        )
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=500,
            detail="Something went wrong while processing the audio. Please try again with a different file.",
        )
    finally:
        try:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass


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
        pipe = PyannotePipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
            use_auth_token=HUGGINGFACE_TOKEN,
        )
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
        return [
            {
                "speaker": "Speaker 1",
                "start": s.get("start", 0.0),
                "end": s.get("end", 0.0),
                "text": (s.get("text") or "").strip(),
            }
            for s in segments
        ]
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
async def export_docx_from_audio_v3(
    file: UploadFile = File(...),
    language: str | None = Form(None),
    translate: str | None = Form(None),
    diarize: str | None = Form(None),
):
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
            raise HTTPException(
                status_code=400,
                detail="No speech was detected in this file. Try a different recording.",
            )

        segments = result.get("segments", [])
        do_diar = (diarize or "").lower() == "true"
        if do_diar:
            wav16k = _convert_to_wav(tmp_path)
            dia = _diarize_segments_dep(wav16k)
            labeled = _assign_speakers(segments, dia)
        else:
            labeled = _assign_speakers(segments, [])

        out = _make_deposition_doc(
            "LucidScript Deposition Transcript",
            result.get("language", "unknown"),
            ((translate or "").lower() == "true"),
            labeled,
        )

        return JSONResponse(
            {
                "message": "Deposition transcript complete. Word doc ready to download.",
                "docx_path": str(out),
                "docx_filename": out.name,
                "language": result.get("language", "unknown"),
                "duration_sec": round(float(result.get("duration", 0)), 2)
                if "duration" in result
                else None,
                "translated": ((translate or "").lower() == "true"),
            }
        )
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=500,
            detail="Something went wrong while processing the audio. Please try a different file.",
        )
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