from fastapi import FastAPI, UploadFile, File, HTTPException
from pydantic import BaseModel
import tempfile, os, pathlib, uuid, re
import whisper
from docx import Document
from datetime import datetime

# start up the app
app = FastAPI()

# load Whisper (tiny model for faster testing)
model = whisper.load_model("tiny")

# folder for any generated files
OUTPUT_DIR = pathlib.Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)

# allowed audio types
ALLOWED_EXTS = {".wav", ".mp3", ".m4a", ".mp4", ".aac", ".flac", ".ogg"}


# simple health check route
@app.get("/")
def home():
    return {"message": "LucidScript backend is running"}


# handles audio uploads and gives back the transcript
@app.post("/transcribe")
async def transcribe_audio(file: UploadFile = File(...)):
    suffix = os.path.splitext(file.filename or "")[-1].lower()
    if suffix not in ALLOWED_EXTS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {suffix}")

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        result = model.transcribe(tmp_path, fp16=False)
        text = result.get("text", "").strip()
        lang = result.get("language")
        dur = result.get("segments", [{}])[-1].get("end") if result.get("segments") else None

        return {
            "filename": file.filename,
            "language": lang,
            "duration_sec": dur,
            "transcript": text
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Transcription failed: {e}")
    finally:
        try:
            os.remove(tmp_path)
        except FileNotFoundError:
            pass


# request model for /format_docx
class FormatRequest(BaseModel):
    raw_text: str


# simple helper to split text into readable paragraphs
def to_paragraphs(text: str):
    text = re.sub(r"\s+", " ", text).strip()
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", text)
    return [p.strip() for p in parts if p.strip()]


# formats the transcript into a docx
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


# combines both steps: transcribe and export to docx in one call
@app.post("/export_docx_from_audio")
async def export_docx_from_audio(file: UploadFile = File(...)):
    # transcribe the audio first
    transcript_data = await transcribe_audio(file)
    text = transcript_data.get("transcript", "")
    if not text:
        raise HTTPException(status_code=500, detail="No transcript text produced.")

    # create the document
    doc = Document()
    doc.add_heading("LucidScript Transcript", 0)
    doc.add_paragraph(datetime.now().strftime("%Y-%m-%d %H:%M"))

    for p in to_paragraphs(text):
        doc.add_paragraph(p)

    out = OUTPUT_DIR / f"lucidscript_{uuid.uuid4().hex[:8]}.docx"
    doc.save(out.as_posix())

    return {
        "message": "Transcription and document export complete.",
        "language": transcript_data.get("language"),
        "duration_sec": transcript_data.get("duration_sec"),
        "docx_path": str(out)
    }

