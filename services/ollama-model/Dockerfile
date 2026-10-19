ARG MODEL_FETCH_BASE_IMAGE=m.daocloud.io/docker.io/library/python:3.12-alpine
FROM ${MODEL_FETCH_BASE_IMAGE}

WORKDIR /app
COPY download_model.py /app/download_model.py

ENTRYPOINT ["python", "/app/download_model.py"]
