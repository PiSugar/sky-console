ARG SERVER_BASE_IMAGE=m.daocloud.io/docker.io/library/python:3.12-slim
FROM ${SERVER_BASE_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN sed -i 's#http://deb.debian.org/debian-security#https://mirrors.aliyun.com/debian-security#g; s#http://deb.debian.org/debian#https://mirrors.aliyun.com/debian#g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update && apt-get install --no-install-recommends -y alsa-utils sox \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt

COPY app ./app

RUN mkdir -p /data

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips", "*"]
