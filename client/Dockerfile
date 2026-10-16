FROM debian:trixie-slim AS readsb-builder

ARG READSB_COMMIT=60d576ba9ecf8815fddcf81f6c585663fb9bf5fa

RUN apt-get update && apt-get install --no-install-recommends -y \
      build-essential \
      ca-certificates \
      git \
      libncurses-dev \
      librtlsdr-dev \
      libusb-1.0-0-dev \
      libzstd-dev \
      pkg-config \
      zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /src/readsb \
    && cd /src/readsb \
    && git init \
    && git remote add origin https://github.com/wiedehopf/readsb.git \
    && (git fetch --depth 1 origin "$READSB_COMMIT" \
        || git fetch --depth 1 origin "$READSB_COMMIT" \
        || git fetch --depth 1 origin "$READSB_COMMIT") \
    && git checkout --detach FETCH_HEAD \
    && make -j"$(nproc)" RTLSDR=yes

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install --no-install-recommends -y \
      ca-certificates \
      libncurses6 \
      librtlsdr0 \
      libusb-1.0-0 \
      libzstd1 \
      zlib1g \
    && rm -rf /var/lib/apt/lists/*

COPY --from=readsb-builder /src/readsb/readsb /usr/local/bin/readsb
COPY agent.py /app/agent.py
COPY entrypoint.sh /app/entrypoint.sh

RUN chmod 755 /app/entrypoint.sh \
    && mkdir -p /data /run/readsb

WORKDIR /app
ENTRYPOINT ["/app/entrypoint.sh"]
