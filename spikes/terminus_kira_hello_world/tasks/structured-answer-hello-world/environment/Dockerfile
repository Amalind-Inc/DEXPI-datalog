FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends tmux \
    && useradd --create-home --shell /bin/bash agent \
    && mkdir /input /workspace \
    && chown root:root /input \
    && chmod 0555 /input \
    && chown agent:agent /workspace \
    && rm -rf /var/lib/apt/lists/*

COPY drawing.json /input/drawing.json
RUN chown root:root /input/drawing.json \
    && chmod 0444 /input/drawing.json

WORKDIR /workspace
USER agent
