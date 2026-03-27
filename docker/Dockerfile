FROM python:3.13-slim

# Create non-root user
RUN groupadd --gid 1000 astridr && \
    useradd --uid 1000 --gid astridr --create-home astridr

WORKDIR /app

COPY pyproject.toml README.md ./
COPY astridr/ astridr/

# openwakeword hard-depends on tflite-runtime which is dead (no Python 3.12+ wheels).
# Install everything except wakeword, then add openwakeword --no-deps + ai-edge-litert.
RUN pip install --no-cache-dir ".[embeddings,media,voice,browser,automation,google]" && \
    pip install --no-cache-dir --no-deps openwakeword && \
    pip install --no-cache-dir ai-edge-litert onnxruntime && \
    chown -R astridr:astridr /app && \
    mkdir -p /home/astridr/.astridr/media/tts && \
    chown -R astridr:astridr /home/astridr/.astridr

USER astridr

EXPOSE 8080 8099

HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8099/health/ready')" || exit 1

CMD ["python", "-m", "astridr"]
