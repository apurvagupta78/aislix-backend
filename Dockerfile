FROM alpine:3.20 AS lfs-fetch

RUN apk add --no-cache git git-lfs curl

ARG GIT_REPO=https://github.com/apurvagupta78/aislix-backend.git
ARG GIT_BRANCH=main
ARG GITHUB_TOKEN=""
# Railway passes service variables matching these ARG names at build time.
ARG SUPABASE_URL=""
ARG SUPABASE_SERVICE_ROLE_KEY=""
ARG LEARNED_CATALOG_BUCKET="catalog-data"

COPY scripts/fetch_retailklip_docker.sh /fetch_retailklip_docker.sh
RUN chmod +x /fetch_retailklip_docker.sh && /fetch_retailklip_docker.sh /src/models

FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-paddle.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir paddlepaddle==3.0.0 \
        -i https://www.paddlepaddle.org.cn/packages/stable/cpu/ \
    && pip install --no-cache-dir -r requirements-paddle.txt

COPY . .

# Overwrite any Git LFS pointer stub with the full checkpoint from the fetch stage.
COPY --from=lfs-fetch /src/models/retailklip_vitb32.pt models/retailklip_vitb32.pt

RUN python scripts/verify_retailklip_checkpoint.py \
    && python scripts/verify_paddle_ocr.py

ENV HOME=/app
ENV OCR_ENGINE=paddle
ENV USE_RETAILKLIP=true
ENV RECOGNITION_STRICT=true
ENV RECOGNITION_V3=false
ENV FAISS_STRICT_THRESHOLD=0.97
ENV FAISS_STRICT_LEARNED_MIN=0.99

EXPOSE 8080

CMD ["python", "run.py"]
