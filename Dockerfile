FROM alpine:3.20 AS lfs-fetch

RUN apk add --no-cache git git-lfs

ARG GIT_REPO=https://github.com/apurvagupta78/aislix-backend.git
ARG GIT_BRANCH=main
ARG GITHUB_TOKEN=""

# Railway Docker builds omit .git, so clone + LFS pull fetches the real checkpoint.
RUN set -eux; \
    REPO="${GIT_REPO}"; \
    if [ -n "${GITHUB_TOKEN}" ]; then \
      REPO="https://${GITHUB_TOKEN}@github.com/apurvagupta78/aislix-backend.git"; \
    fi; \
    git lfs install; \
    git clone --depth 1 --branch "${GIT_BRANCH}" "${REPO}" /src; \
    cd /src; \
    git lfs pull; \
    test "$(wc -c < models/retailklip_vitb32.pt)" -gt 1000000; \
    echo "RetailKLIP LFS fetch OK: $(wc -c < models/retailklip_vitb32.pt) bytes"

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
ENV OCR_ENGINE=easyocr
ENV USE_RETAILKLIP=true

EXPOSE 8080

CMD ["python", "run.py"]
