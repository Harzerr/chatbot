#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_DIR="${TARGET_DIR:-${PROJECT_DIR}/qdrant_storage}"
IMPORT_ARCHIVE="${IMPORT_ARCHIVE:-${PROJECT_DIR}/qdrant_data.tar.gz}"
WORK_DIR="${PROJECT_DIR}/.qdrant_restore_work"
EXTRACT_DIR="${WORK_DIR}/extracted"
CONTAINER_ID="${QDRANT_CONTAINER_ID:-1f1f2ed290e036063fe46057236c9b9bf8fbd613f838a5bca0f263db2cdb3a0e}"
TIMESTAMP="$(date +%F_%H-%M-%S)"
BACKUP_DIR="${PROJECT_DIR}/qdrant_storage.pre_restore_${TIMESTAMP}"

log() {
  echo "[restore_qdrant_storage] $*"
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required command: $1" >&2
    exit 1
  }
}

main() {
  require_cmd docker
  require_cmd tar
  require_cmd rsync

  [[ -f "${IMPORT_ARCHIVE}" ]] || {
    echo "Import archive not found: ${IMPORT_ARCHIVE}" >&2
    exit 1
  }

  mkdir -p "${EXTRACT_DIR}"
  rm -rf "${EXTRACT_DIR}"
  mkdir -p "${EXTRACT_DIR}"

  log "Stopping qdrant container ${CONTAINER_ID}"
  docker stop "${CONTAINER_ID}" >/dev/null

  log "Extracting ${IMPORT_ARCHIVE}"
  tar -xzf "${IMPORT_ARCHIVE}" -C "${EXTRACT_DIR}"

  [[ -d "${EXTRACT_DIR}/collections" ]] || {
    echo "Extracted archive does not look like a qdrant storage directory: ${EXTRACT_DIR}" >&2
    exit 1
  }

  log "Backing up current storage to ${BACKUP_DIR}"
  cp -a "${TARGET_DIR}" "${BACKUP_DIR}"

  log "Replacing ${TARGET_DIR}"
  rm -rf "${TARGET_DIR}"
  mkdir -p "${TARGET_DIR}"
  rsync -a "${EXTRACT_DIR}/" "${TARGET_DIR}/"

  log "Starting qdrant container ${CONTAINER_ID}"
  docker start "${CONTAINER_ID}" >/dev/null

  log "Done"
  log "Backup: ${BACKUP_DIR}"
  log "Next step: restart backend/workers if they cache qdrant connections"
}

main "$@"
