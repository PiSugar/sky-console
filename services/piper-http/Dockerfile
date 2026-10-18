FROM python:3.12-bookworm

ARG VOICE_NAME=en_US-ryan-medium
ENV PIPER_VOICE=${VOICE_NAME}
WORKDIR /data
RUN pip install --no-cache-dir "piper-tts[http]==1.3.0" \
    && python -m piper.download_voices "${VOICE_NAME}"
EXPOSE 8805
CMD ["sh", "-c", "python -m piper.http_server -m ${PIPER_VOICE} --host 0.0.0.0 --port 8805"]
