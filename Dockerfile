FROM python:3.10-slim

ARG TARGETARCH
ENV SE_CHROMEDRIVER=/usr/bin/chromedriver \
    PTB_TIMEDELTA=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends chromium chromium-driver tzdata \
    && rm -rf /var/lib/apt/lists/*
ADD --chmod=755 https://github.com/aptible/supercronic/releases/download/v0.2.49/supercronic-linux-${TARGETARCH} /usr/local/bin/supercronic

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
