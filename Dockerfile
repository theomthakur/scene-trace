# SceneTrace live backend: API + worker share this image. CPU inference only. Build: docker build -t scenetrace .
FROM node:22-slim AS web
WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.11-slim AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.docker.txt .
# CPU-only PyTorch wheels (the default Linux wheels are several GB larger because they bundle CUDA)
RUN pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.docker.txt
COPY pyproject.toml ./
COPY src ./src
COPY config ./config
RUN pip install --no-cache-dir --no-deps -e .
COPY --from=web /app/web/dist ./web/dist
RUN useradd --create-home --uid 10001 app && mkdir -p /data && chown app:app /data
USER app
ENV VI_DATA_DIR=/data VI_WEB_DIST=/app/web/dist TORCH_HOME=/data/torch HF_HOME=/data/hf PYTHONUNBUFFERED=1
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status==200 else 1)"
CMD ["uvicorn", "video_investigator.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
