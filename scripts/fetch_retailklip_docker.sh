#!/bin/sh
# Fetch RetailKLIP checkpoint for Docker build (Railway has no .git / LFS in context).
# Order: Supabase storage (uses existing Railway vars) → Git LFS (optional GITHUB_TOKEN).
set -eu

DEST_DIR="${1:-/src/models}"
mkdir -p "${DEST_DIR}"
CHECKPOINT="${DEST_DIR}/retailklip_vitb32.pt"
MIN_BYTES=1000000

fetch_supabase() {
  if [ -z "${SUPABASE_URL:-}" ] || [ -z "${SUPABASE_SERVICE_ROLE_KEY:-}" ]; then
    return 1
  fi
  BASE="${SUPABASE_URL%/}"
  BUCKET="${LEARNED_CATALOG_BUCKET:-catalog-data}"
  OBJECT="retailklip_vitb32.pt"
  echo "Fetching RetailKLIP from Supabase storage (${BUCKET}/${OBJECT})..."
  if curl -fsSL \
    -H "apikey: ${SUPABASE_SERVICE_ROLE_KEY}" \
    -H "Authorization: Bearer ${SUPABASE_SERVICE_ROLE_KEY}" \
    "${BASE}/storage/v1/object/${BUCKET}/${OBJECT}" \
    -o "${CHECKPOINT}"; then
    SIZE="$(wc -c < "${CHECKPOINT}")"
    echo "Supabase fetch: ${SIZE} bytes"
    [ "${SIZE}" -gt "${MIN_BYTES}" ]
    return 0
  fi
  rm -f "${CHECKPOINT}"
  return 1
}

fetch_git_lfs() {
  REPO="${GIT_REPO:-https://github.com/apurvagupta78/aislix-backend.git}"
  BRANCH="${GIT_BRANCH:-main}"
  if [ -n "${GITHUB_TOKEN:-}" ]; then
    REPO="https://${GITHUB_TOKEN}@github.com/apurvagupta78/aislix-backend.git"
    echo "Fetching RetailKLIP via Git LFS (authenticated)..."
  else
    echo "Fetching RetailKLIP via Git LFS (anonymous — may fail; set GITHUB_TOKEN on Railway)..."
  fi
  WORK="/tmp/aislix-lfs"
  rm -rf "${WORK}"
  git lfs install
  if ! git clone --depth 1 --branch "${BRANCH}" "${REPO}" "${WORK}"; then
    echo "git clone failed" >&2
    rm -rf "${WORK}"
    return 1
  fi
  cd "${WORK}"
  if ! git lfs pull; then
    echo "git lfs pull failed" >&2
    cd /
    rm -rf "${WORK}"
    return 1
  fi
  if [ ! -f "${WORK}/models/retailklip_vitb32.pt" ]; then
    echo "checkpoint missing after git lfs pull" >&2
    cd /
    rm -rf "${WORK}"
    return 1
  fi
  cp "${WORK}/models/retailklip_vitb32.pt" "${CHECKPOINT}"
  SIZE="$(wc -c < "${CHECKPOINT}")"
  echo "Git LFS fetch: ${SIZE} bytes"
  cd /
  rm -rf "${WORK}"
  [ "${SIZE}" -gt "${MIN_BYTES}" ]
}

if fetch_supabase; then
  echo "RetailKLIP ready (Supabase)"
  exit 0
fi

if [ -f "${CHECKPOINT}" ] && [ "$(wc -c < "${CHECKPOINT}")" -gt "${MIN_BYTES}" ]; then
  echo "RetailKLIP already present in build context"
  exit 0
fi

if fetch_git_lfs; then
  echo "RetailKLIP ready (Git LFS)"
  exit 0
fi

echo "ERROR: Could not fetch retailklip_vitb32.pt (>1 MB required)." >&2
echo "Fix: ensure SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY are Railway service variables" >&2
echo "     and retailklip_vitb32.pt is uploaded to Supabase catalog-data bucket," >&2
echo "     OR add GITHUB_TOKEN (GitHub PAT, repo read) as a Railway build variable." >&2
exit 1
