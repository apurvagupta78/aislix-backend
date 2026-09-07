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

# RetailKLIP (~335 MB) is Git LFS. Railway Docker builds often get only the pointer stub.
# Do NOT fail the build — OpenAI vision scans (SCAN_PROVIDER=openai) do not need it bundled.
# At runtime, ensure_checkpoint() in app/retailklip.py downloads from Supabase when configured.
RUN if [ -f models/retailklip_vitb32.pt ] && [ "$(wc -c < models/retailklip_vitb32.pt)" -gt 1000000 ]; then \
      echo "RetailKLIP bundled: $(wc -c < models/retailklip_vitb32.pt) bytes"; \
    else \
      rm -f models/retailklip_vitb32.pt 2>/dev/null || true; \
      echo "RetailKLIP not bundled at build — optional Supabase download at startup"; \
    fi

RUN python scripts/verify_paddle_ocr.py

ENV HOME=/app
ENV OCR_ENGINE=paddle
ENV USE_RETAILKLIP=true
ENV RECOGNITION_STRICT=true
ENV RECOGNITION_V3=false
ENV FAISS_STRICT_THRESHOLD=0.97
ENV FAISS_STRICT_LEARNED_MIN=0.99

EXPOSE 8080

CMD ["python", "run.py"]
