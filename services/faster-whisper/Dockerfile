FROM python:3.12-bookworm

ARG MODEL_SIZE=tiny.en
ENV HF_HOME=/models \
    HF_HUB_DISABLE_XET=1
WORKDIR /app
RUN apt-get update && apt-get install --no-install-recommends -y ffmpeg \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('${MODEL_SIZE}', device='cpu', compute_type='int8')"
COPY server.py ./
EXPOSE 8803
CMD ["python", "/app/server.py"]
