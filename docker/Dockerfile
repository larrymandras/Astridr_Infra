FROM python:3.13-slim

# Create non-root user
RUN groupadd --gid 1000 astridr && \
    useradd --uid 1000 --gid astridr --create-home astridr

WORKDIR /app

COPY pyproject.toml .
COPY astridr/ astridr/

RUN pip install --no-cache-dir ".[all]" && \
    chown -R astridr:astridr /app

USER astridr

EXPOSE 8080 8099

HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8099/health/ready')" || exit 1

CMD ["python", "-m", "astridr"]
