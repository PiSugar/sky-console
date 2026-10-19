ARG ASR_BASE_IMAGE=m.daocloud.io/docker.io/library/python:3.12-bookworm
FROM ${ASR_BASE_IMAGE}

ENV HF_HOME=/models \
    HF_ENDPOINT=https://hf-mirror.net \
    MODEL_DOWNLOAD_ENDPOINT=https://modelscope.cn/models/pengzhendong \
    HF_HUB_DISABLE_XET=1
WORKDIR /app
COPY requirements.txt ./
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
RUN python -c "import faster_whisper, flask" 2>/dev/null \
    || pip install --no-cache-dir --index-url "${PIP_INDEX_URL}" -r requirements.txt
ARG MODEL_SIZE=small.en
COPY download_model.py ./
RUN python download_model.py --model "${MODEL_SIZE}" --metadata-endpoint "${HF_ENDPOINT}" --download-endpoint "${MODEL_DOWNLOAD_ENDPOINT}" --output "/models/${MODEL_SIZE}"
COPY server.py ./
EXPOSE 8803
CMD ["python", "/app/server.py"]
