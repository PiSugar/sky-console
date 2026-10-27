ARG HARDWARE_BASE_IMAGE=m.daocloud.io/docker.io/library/python:3.12-slim
FROM ${HARDWARE_BASE_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

RUN sed -i 's#http://deb.debian.org/debian-security#https://mirrors.aliyun.com/debian-security#g; s#http://deb.debian.org/debian#https://mirrors.aliyun.com/debian#g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update && apt-get install --no-install-recommends -y \
      alsa-utils \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple gpiod==2.2.0 smbus2==0.5.0

WORKDIR /app
COPY hardware_bridge.py /app/hardware_bridge.py

CMD ["python", "/app/hardware_bridge.py"]
