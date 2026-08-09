FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    git \
    git-lfs \
    && git lfs install \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source (.git included so we can materialize LFS objects during build).
COPY . .

# Pull Git LFS checkpoint into the image (Railway clone often leaves pointer stubs).
RUN set -eux; \
    if [ -d .git ]; then \
      git lfs pull; \
    fi; \
    python scripts/verify_retailklip_checkpoint.py; \
    rm -rf .git

ENV USE_RETAILKLIP=true

EXPOSE 8080

CMD ["python", "run.py"]
