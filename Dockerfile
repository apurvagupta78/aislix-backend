FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    curl \
    git \
    git-lfs \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-paddle.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir paddlepaddle==3.0.0 \
        -i https://www.paddlepaddle.org.cn/packages/stable/cpu/ \
    && pip install --no-cache-dir -r requirements-paddle.txt

COPY . .

# Railway runs `git lfs pull` in buildCommand before docker build (GitHub-authenticated).
# If the checkpoint is still an LFS pointer stub, fetch via Supabase or GITHUB_TOKEN.
ARG GITHUB_TOKEN=""
ARG SUPABASE_URL=""
ARG SUPABASE_SERVICE_ROLE_KEY=""
ARG LEARNED_CATALOG_BUCKET="catalog-data"

COPY scripts/fetch_retailklip_docker.sh /fetch_retailklip_docker.sh
RUN chmod +x /fetch_retailklip_docker.sh \
    && if [ ! -f models/retailklip_vitb32.pt ] \
         || [ "$(wc -c < models/retailklip_vitb32.pt)" -lt 1000000 ]; then \
         /fetch_retailklip_docker.sh /app/models; \
       else \
         echo "RetailKLIP checkpoint present in build context: $(wc -c < models/retailklip_vitb32.pt) bytes"; \
       fi

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
