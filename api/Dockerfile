FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py /app/

EXPOSE 8090

CMD ["gunicorn", "-b", "0.0.0.0:8090", "app:app", "--workers", "2", "--threads", "4", "--timeout", "120"]
