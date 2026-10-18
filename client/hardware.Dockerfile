FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install --no-install-recommends -y \
      alsa-utils \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir gpiod==2.2.0 smbus2==0.5.0

WORKDIR /app
COPY hardware_bridge.py /app/hardware_bridge.py

CMD ["python", "/app/hardware_bridge.py"]
