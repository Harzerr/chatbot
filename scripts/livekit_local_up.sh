#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LIVEKIT_DIR="${PROJECT_DIR}/tools/livekit"
COMPOSE_FILE="${LIVEKIT_DIR}/docker-compose.yml"
MIRROR_IMAGE="swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/livekit/livekit-server:latest"
OFFICIAL_IMAGE="docker.io/livekit/livekit-server:latest"
DOCKER_CMD=()
DEFAULT_LOCAL_TAR="/home/yons/DATA/yql_3/livekit-server-latest.tar"
LOCAL_TAR_CANDIDATES=(
  "${LIVEKIT_IMAGE_TAR:-}"
  "${DEFAULT_LOCAL_TAR}"
  "/home/yons/DATA/yql_3/livekit-livekit-server-latest.tar"
  "/home/yons/DATA/yql_3/livekit-server.tar"
  "/home/yons/DATA/yql_3/livekit.tar"
)

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
  echo "[livekit_local_up] failed: cannot access docker daemon."
  echo "Run one of the following:"
  echo "  1) sudo usermod -aG docker ${USER}  # then re-login"
  echo "  2) if you have local tar:"
  echo "     sudo docker load -i ${DEFAULT_LOCAL_TAR}"
  echo "     sudo docker compose -f ${COMPOSE_FILE} up -d"
  echo "  3) or pull from mirror:"
  echo "     sudo docker pull ${MIRROR_IMAGE}"
  echo "     sudo docker tag ${MIRROR_IMAGE} ${OFFICIAL_IMAGE}"
  echo "     sudo docker compose -f ${COMPOSE_FILE} up -d"
  exit 1
fi

find_local_tar() {
  local candidate
  for candidate in "${LOCAL_TAR_CANDIDATES[@]}"; do
    [[ -n "${candidate}" ]] || continue
    [[ -f "${candidate}" ]] || continue
    printf '%s' "${candidate}"
    return 0
  done

  candidate="$(find /home/yons/DATA/yql_3 -maxdepth 1 -type f \( -iname '*livekit*.tar' -o -iname '*livekit*.tar.gz' -o -iname '*livekit*.tgz' \) | head -n 1 || true)"
  if [[ -n "${candidate}" ]]; then
    printf '%s' "${candidate}"
    return 0
  fi

  return 1
}

ensure_official_image() {
  local candidate_image

  if "${DOCKER_CMD[@]}" image inspect "${OFFICIAL_IMAGE}" >/dev/null 2>&1; then
    return 0
  fi

  if "${DOCKER_CMD[@]}" image inspect "${MIRROR_IMAGE}" >/dev/null 2>&1; then
    "${DOCKER_CMD[@]}" tag "${MIRROR_IMAGE}" "${OFFICIAL_IMAGE}"
    return 0
  fi

  candidate_image="$("${DOCKER_CMD[@]}" images --format '{{.Repository}}:{{.Tag}}' | grep -E '(^|/)livekit/livekit-server:' | head -n 1 || true)"
  if [[ -n "${candidate_image}" ]]; then
    "${DOCKER_CMD[@]}" tag "${candidate_image}" "${OFFICIAL_IMAGE}"
    return 0
  fi

  return 1
}

echo "[livekit_local_up] ensuring image exists..."
if ! ensure_official_image; then
  LOCAL_TAR_PATH="$(find_local_tar || true)"
  if [[ -n "${LOCAL_TAR_PATH}" ]]; then
    echo "[livekit_local_up] loading local image tar: ${LOCAL_TAR_PATH}"
    "${DOCKER_CMD[@]}" load -i "${LOCAL_TAR_PATH}"
    ensure_official_image || true
  fi
fi

if ! ensure_official_image; then
  echo "[livekit_local_up] local tar not found or does not contain livekit/livekit-server; pulling from mirror..."
  "${DOCKER_CMD[@]}" pull "${MIRROR_IMAGE}"
  "${DOCKER_CMD[@]}" tag "${MIRROR_IMAGE}" "${OFFICIAL_IMAGE}"
fi

echo "[livekit_local_up] starting local LiveKit server..."
"${DOCKER_CMD[@]}" compose -f "${COMPOSE_FILE}" up -d

echo ""
echo "[livekit_local_up] started."
echo "Set project .env like this:"
echo "  LIVEKIT_URL=wss://<your-domain>"
echo "  LIVEKIT_INTERNAL_URL=ws://127.0.0.1:7880"
echo "  LIVEKIT_PUBLIC_URL=wss://<your-domain>"
echo "  LIVEKIT_API_KEY=devkey"
echo "  LIVEKIT_API_SECRET=secret"
echo ""
echo "For same-host quick test only (no external browser):"
echo "  LIVEKIT_URL=ws://127.0.0.1:7880"
echo "  LIVEKIT_INTERNAL_URL=ws://127.0.0.1:7880"
echo "  LIVEKIT_PUBLIC_URL=ws://127.0.0.1:7880"
