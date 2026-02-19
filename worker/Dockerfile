FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
  && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir faster-whisper==1.1.0 requests

WORKDIR /app
COPY worker.py /app/worker.py

CMD ["python", "/app/worker.py"]
