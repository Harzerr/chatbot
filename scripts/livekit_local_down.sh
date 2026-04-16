#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${PROJECT_DIR}/tools/livekit/docker-compose.yml"
DOCKER_CMD=()

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is not installed."
  exit 1
fi

if [[ ! -f "${COMPOSE_FILE}" ]]; then
  echo "missing compose file: ${COMPOSE_FILE}"
  exit 1
fi

if docker info >/dev/null 2>&1; then
  DOCKER_CMD=(docker)
elif sudo -n docker info >/dev/null 2>&1; then
  DOCKER_CMD=(sudo -n docker)
else
  echo "[livekit_local_down] failed: cannot access docker daemon."
  echo "Run manually with sudo:"
  echo "  sudo docker compose -f ${COMPOSE_FILE} down"
  exit 1
fi

echo "[livekit_local_down] stopping local LiveKit server..."
"${DOCKER_CMD[@]}" compose -f "${COMPOSE_FILE}" down
echo "[livekit_local_down] stopped."
