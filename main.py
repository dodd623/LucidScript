from fastapi import FastAPI, UploadFile, File
from pydantic import BaseModel
import tempfile, os, pathlib, uuid, re
import whisper
from docx import Document
from datetime import datetime

# start up the app
app = FastAPI()

# load Whisper (tiny model for faster testing)
model = whisper.load_model("tiny")


# # quick check route, used for testing the local server (not necessarily needed now)
# @app.get("/")
# def home():
#     return {"message": "LucidScript backend is running"}


# handles audio uploads and gives back the transcript
@app.post("/transcribe")
async def transcribe_audio(file: UploadFile = File(...)):
    suffix = os.path.splitext(file.filename)[-1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    result = model.transcribe(tmp_path)
    text = result.get("text", "").strip()

    os.remove(tmp_path)

    return {"transcript": text}


# folder for any generated files
OUTPUT_DIR = pathlib.Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)

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


# end of file — everything below this line should just work