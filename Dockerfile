# Use slim python image
FROM python:3.11-slim

# Install ffmpeg for whisper
RUN apt-get update && apt-get install -y ffmpeg && apt-get clean

# Set work directory
WORKDIR /app

# Copy dependencies
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy rest of the app
COPY . .

# Expose port for Fly.io
EXPOSE 8080

# Create the output folder if missing
RUN mkdir -p /app/output

ENV PYTHONUNBUFFERED=1

# Command for Fly.io
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]