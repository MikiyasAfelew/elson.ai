FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# The app runs as an unprivileged user, so it needs a directory it may write generated audio to.
RUN useradd --system --no-create-home elson \
    && mkdir -p /var/lib/elson/audio \
    && chown -R elson /var/lib/elson
ENV ELSON_AUDIO_DIR=/var/lib/elson/audio
USER elson

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
