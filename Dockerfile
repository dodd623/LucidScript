FROM python:3.11-slim

# System packages Whisper + OCR depend on
RUN apt-get update && apt-get install -y \
    ffmpeg \
    tesseract-ocr \
    && apt-get clean

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
