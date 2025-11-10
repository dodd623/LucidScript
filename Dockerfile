# Dockerfile
FROM python:3.11-slim

# system deps (ffmpeg) — keep image small
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
 && rm -rf /var/lib/apt/lists/*

# app dir
WORKDIR /app

# install deps first (better cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# copy code
COPY . .

# Render sets PORT env var; bind to 0.0.0.0
ENV PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "${PORT}"]
