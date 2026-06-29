#!/usr/bin/env bash
# scripts/apply-patches.sh
#
# Populate ./patches/ with the Autotoll Devops brand-rebadge bundle
# (baked JS, favicons, promo HTML, urls.py) from the official release
# tarball. The compose file bind-mounts files from ./patches/ into the
# running container, so this script MUST run before `docker compose up`.
#
# Usage:
#   ./scripts/apply-patches.sh                # use default release URL
#   PATCHES_URL=https://.../sxdevops-patches-v0.1.0.tgz ./scripts/apply-patches.sh
#   ./scripts/apply-patches.sh --local ./patches.tgz
#
# Exit codes:
#   0  patches/ populated and non-empty
#   1  download / extract failed
#   2  patches/ ended up empty or missing required files

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PATCHES_DIR="${REPO_ROOT}/patches"

DEFAULT_URL="${PATCHES_URL:-https://github.com/z351150948/devops/releases/download/v0.1.0/sxdevops-patches-v0.1.0.tgz}"

# ---- args ------------------------------------------------------------------
LOCAL_TARBALL=""
if [ "${1:-}" = "--local" ]; then
  LOCAL_TARBALL="${2:?usage: $0 --local <path-to-tarball>}"
fi

# ---- helpers ---------------------------------------------------------------
log()  { printf '\033[1;34m[apply-patches]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[apply-patches]\033[0m %s\n' "$*" >&2; }
fail() { printf '\033[1;31m[apply-patches]\033[0m %s\n' "$*" >&2; exit 1; }

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "missing required command: $1"
}

REQUIRED_FILES=(
  "index.html"
  "favicon.png"
  "favicon.svg"
  "sxdevops-ai-agent-promo.html"
  "urls.py"
  "assets/index-DVQYMGEu.js"
  "assets/Login-dq9xDgTt.js"
  "assets/WebShell-D2GcyKzp.js"
  "assets/K8sManage-BcAvxaTu.js"
  "assets/AIAgentPromo-CMRKMGzn.js"
)

verify_patches_dir() {
  local missing=0
  for f in "${REQUIRED_FILES[@]}"; do
    if [ ! -s "${PATCHES_DIR}/${f}" ]; then
      warn "missing or empty: patches/${f}"
      missing=1
    fi
  done
  return "${missing}"
}

# ---- main ------------------------------------------------------------------
require_cmd tar
require_cmd curl

# Skip if already populated
if verify_patches_dir >/dev/null 2>&1; then
  log "patches/ already populated; nothing to do"
  exit 0
fi

mkdir -p "${PATCHES_DIR}"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

if [ -n "${LOCAL_TARBALL}" ]; then
  [ -f "${LOCAL_TARBALL}" ] || fail "local tarball not found: ${LOCAL_TARBALL}"
  log "using local tarball: ${LOCAL_TARBALL}"
  cp "${LOCAL_TARBALL}" "${TMP_DIR}/patches.tgz"
else
  log "downloading patches from ${DEFAULT_URL}"
  if ! curl -fsSL --retry 3 -o "${TMP_DIR}/patches.tgz" "${DEFAULT_URL}"; then
    fail "download failed; check network / PATCHES_URL / --local <path>"
  fi
fi

log "extracting"
tar -xzf "${TMP_DIR}/patches.tgz" -C "${TMP_DIR}"

# Find the actual root of the tarball (some tarballs include a top-level dir)
SRC_ROOT="${TMP_DIR}"
if [ ! -f "${SRC_ROOT}/index.html" ]; then
  for d in "${TMP_DIR}"/*/; do
    if [ -f "${d}index.html" ]; then
      SRC_ROOT="${d%/}"
      break
    fi
  done
fi

# Replace contents (do not leave stale files from a previous release)
rm -rf "${PATCHES_DIR:?}"/*
cp -a "${SRC_ROOT}/." "${PATCHES_DIR}/"

if ! verify_patches_dir; then
  fail "patches/ is missing required files after extract; see warnings above"
fi

log "patches/ ready (contents: $(du -sh "${PATCHES_DIR}" | cut -f1))"
log "next: docker compose up -d"
