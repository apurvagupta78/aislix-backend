"""Railway entrypoint: bind 0.0.0.0 on the injected PORT."""

from __future__ import annotations

import os
import sys


def main() -> None:
    port = int(os.environ.get("PORT") or "8080")
    print(f"Starting Aislix on 0.0.0.0:{port}", flush=True)
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        log_level="info",
        proxy_headers=True,
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("Aislix failed to start:", file=sys.stderr, flush=True)
        raise
