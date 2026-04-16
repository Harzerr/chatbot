#!/usr/bin/env bash
set -Eeuo pipefail

# ========= 闇€瑕佹寜浣犵殑瀹為檯鐜淇敼鐨勫彉閲?=========
SESSION_NAME="${SESSION_NAME:-chatbot_stack}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${PROJECT_DIR:-${SCRIPT_DIR}}"
CONDA_BASE="${CONDA_BASE:-/home/NEIC_LAB/anaconda/Anaconda3}"
CONDA_ENV="${CONDA_ENV:-chatbot313}"
FRONTEND_DIR="${FRONTEND_DIR:-${PROJECT_DIR}/frontend}"
JUDGE0_DIR="${JUDGE0_DIR:-${PROJECT_DIR}/tools/judge0-v1.13.1}"

# 鏃ュ織鐩綍
LOG_ROOT="${LOG_ROOT:-${PROJECT_DIR}/logs}"

# 鍓嶅悗绔鍙?BACKEND_PORT="8000"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"

# 鍓嶇鍚姩鍛戒护
FRONTEND_CMD="${FRONTEND_CMD:-npm start}"

# 鍚庣鍚姩鍛戒护
BACKEND_CMD="${BACKEND_CMD:-python app.py}"

# LiveKit 鍚姩鍛戒护
LIVEKIT_CMD="${LIVEKIT_CMD:-python app/agent/livekit_agent.py dev}"

# Judge0 鍚姩鍛戒护
JUDGE0_COMPOSE_CMD="${JUDGE0_COMPOSE_CMD:-docker compose up -d}"
JUDGE0_COMPOSE_SUDO_CMD="${JUDGE0_COMPOSE_SUDO_CMD:-sudo -n docker compose up -d}"

# Qdrant 鍚姩鍛戒护
QDRANT_CONTAINER_NAME="${QDRANT_CONTAINER_NAME:-qdrant}"
QDRANT_START_CMD="${QDRANT_START_CMD:-docker start ${QDRANT_CONTAINER_NAME}}"
QDRANT_START_SUDO_CMD="${QDRANT_START_SUDO_CMD:-sudo -n docker start ${QDRANT_CONTAINER_NAME}}"

# MCP 鍛戒护
MCP_SEARCH_CMD="${MCP_SEARCH_CMD:-python -m app.mcp_server.search_server}"
MCP_SCRAPE_CMD="${MCP_SCRAPE_CMD:-python -m app.mcp_server.web_scrapping_server}"
TMUX_HISTORY_LIMIT="${TMUX_HISTORY_LIMIT:-100000}"
USE_TIMESTAMP_LOG_DIR="${USE_TIMESTAMP_LOG_DIR:-1}"
CLEAR_INHERITED_PROXY="${CLEAR_INHERITED_PROXY:-1}"

# tmux 鍘嗗彶缂撳啿鍖?TMUX_HISTORY_LIMIT="100000"

# 鏄惁涓烘瘡娆″惎鍔ㄥ垱寤哄崟鐙棩蹇楃洰褰曪細1=鏄紝0=鍚?USE_TIMESTAMP_LOG_DIR="1"

# 鏄惁娓呯悊浠庣埗缁堢/VSCode 缁ф壙鏉ョ殑鏍囧噯浠ｇ悊鍙橀噺锛?=鏄紝0=鍚?# LiveKit 濡傞渶浠ｇ悊锛岃浼樺厛鍦?.env 涓樉寮忚缃?LIVEKIT_API_HTTP_PROXY / LIVEKIT_AGENT_HTTP_PROXY銆?CLEAR_INHERITED_PROXY="${CLEAR_INHERITED_PROXY:-1}"
# ============================================

ENV_FILE="${PROJECT_DIR}/.env"
BASE_NO_PROXY="localhost,127.0.0.1,::1"
LOCAL_NO_PROXY="${BASE_NO_PROXY}"

log() {
  echo "[start_chatbot_stack] $*"
}

strip_wrapping_quotes() {
  local value="$1"
  value="${value%\"}"
  value="${value#\"}"
  value="${value%\'}"
  value="${value#\'}"
  printf '%s' "${value}"
}

append_csv_unique() {
  local csv="$1"
  local item="$2"
  item="$(strip_wrapping_quotes "${item}")"
  [[ -n "${item}" ]] || {
    printf '%s' "${csv}"
    return
  }

  if [[ -z "${csv}" ]]; then
    printf '%s' "${item}"
    return
  fi

  case ",${csv}," in
    *,"${item}",*)
      printf '%s' "${csv}"
      ;;
    *)
      printf '%s,%s' "${csv}" "${item}"
      ;;
  esac
}

get_env_value() {
  local key="$1"
  [[ -f "${ENV_FILE}" ]] || return 0

  local line
  line="$(grep -E "^${key}=" "${ENV_FILE}" | tail -n 1 || true)"
  [[ -n "${line}" ]] || return 0

  line="${line#*=}"
  line="${line%$'\r'}"
  strip_wrapping_quotes "${line}"
}

extract_host_from_url() {
  local url="$1"
  [[ -n "${url}" ]] || return 0

  url="${url#*://}"
  url="${url%%/*}"
  url="${url##*@}"

  if [[ "${url}" == \[*\]* ]]; then
    url="${url#\[}"
    url="${url%%\]*}"
  else
    url="${url%%:*}"
  fi

  printf '%s' "${url}"
}

is_private_host() {
  local host="$1"
  case "${host}" in
    localhost|127.*|::1|10.*|192.168.*|172.1[6-9].*|172.2[0-9].*|172.3[0-1].*)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

build_local_no_proxy() {
  local merged="${BASE_NO_PROXY}"
  local qdrant_host
  local service_host
  local key

  qdrant_host="$(get_env_value "QDRANT_HOST")"
  merged="$(append_csv_unique "${merged}" "${qdrant_host}")"

  for key in STT_API_URL LLM_API_URL TTS_API_URL JUDGE0_API_URL; do
    service_host="$(extract_host_from_url "$(get_env_value "${key}")")"
    if is_private_host "${service_host}"; then
      merged="$(append_csv_unique "${merged}" "${service_host}")"
    fi
  done

  printf '%s' "${merged}"
}

apply_proxy_env() {
  local merged="${NO_PROXY:-${no_proxy:-}}"
  local item

  if [[ "${CLEAR_INHERITED_PROXY}" == "1" ]]; then
    unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY
  fi

  LOCAL_NO_PROXY="$(build_local_no_proxy)"
  IFS=',' read -r -a no_proxy_items <<< "${LOCAL_NO_PROXY}"
  for item in "${no_proxy_items[@]}"; do
    merged="$(append_csv_unique "${merged}" "${item}")"
  done

  export NO_PROXY="${merged}"
  export no_proxy="${merged}"
}

sync_tmux_proxy_env() {
  local var
  for var in http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY NO_PROXY no_proxy; do
    if [[ -n "${!var:-}" ]]; then
      tmux set-environment -t "${SESSION_NAME}" "${var}" "${!var}"
    else
      tmux set-environment -t "${SESSION_NAME}" -r "${var}" 2>/dev/null || true
    fi
  done
}

ensure_tmux() {
  command -v tmux >/dev/null 2>&1 || {
    echo "tmux 鏈畨瑁咃紝璇峰厛鎵ц: sudo apt update && sudo apt install -y tmux"
    exit 1
  }
}

ensure_conda() {
  [[ -f "${CONDA_BASE}/etc/profile.d/conda.sh" ]] || {
    echo "鎵句笉鍒?conda 鍒濆鍖栬剼鏈? ${CONDA_BASE}/etc/profile.d/conda.sh"
    exit 1
  }
}

ensure_dirs() {
  [[ -d "${PROJECT_DIR}" ]] || { echo "椤圭洰鐩綍涓嶅瓨鍦? ${PROJECT_DIR}"; exit 1; }
  [[ -d "${FRONTEND_DIR}" ]] || { echo "鍓嶇鐩綍涓嶅瓨鍦? ${FRONTEND_DIR}"; exit 1; }
  [[ -d "${JUDGE0_DIR}" ]] || { echo "Judge0 鐩綍涓嶅瓨鍦? ${JUDGE0_DIR}"; exit 1; }
  mkdir -p "${LOG_ROOT}"
}

session_exists() {
  tmux has-session -t "${SESSION_NAME}" 2>/dev/null
}

prepare_log_dir() {
  if [[ "${USE_TIMESTAMP_LOG_DIR}" == "1" ]]; then
    RUN_ID="$(date +%F_%H-%M-%S)"
    LOG_DIR="${LOG_ROOT}/${RUN_ID}"
  else
    LOG_DIR="${LOG_ROOT}/latest"
  fi
  mkdir -p "${LOG_DIR}"

  # 缁存姢涓€涓?latest 杞摼鎺ワ紝鏂逛究 tail
  rm -rf "${LOG_ROOT}/latest"
  ln -s "${LOG_DIR}" "${LOG_ROOT}/latest"
}

make_window() {
  local win_name="$1"
  local workdir="$2"
  local cmd="$3"
  local logfile="$4"
  local proxy_cleanup=""

  if [[ "${CLEAR_INHERITED_PROXY}" == "1" ]]; then
    proxy_cleanup="unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY && "
  fi

  tmux new-window -t "${SESSION_NAME}" -n "${win_name}" -c "${workdir}"
  tmux send-keys -t "${SESSION_NAME}:${win_name}" \
    "source '${CONDA_BASE}/etc/profile.d/conda.sh' && \
conda activate '${CONDA_ENV}' && \
${proxy_cleanup}\
cd '${workdir}' && \
echo '[${win_name}] logging to ${logfile}' && \
(${cmd}) 2>&1 | tee -a '${logfile}'" C-m
}

wait_for_tcp() {
  local host="$1"
  local port="$2"
  local label="$3"
  local attempts="${4:-30}"
  local i

  if [[ "${host}" == "localhost" ]]; then
    host="127.0.0.1"
  fi

  for ((i = 1; i <= attempts; i++)); do
    if timeout 1 bash -c "cat < /dev/null > /dev/tcp/${host}/${port}" >/dev/null 2>&1; then
      echo "[${label}] ready at ${host}:${port}"
      return 0
    fi
    sleep 1
  done

  echo "[${label}] still not reachable at ${host}:${port} after ${attempts}s"
  return 1
}

start_qdrant_if_possible() {
  local logfile="$1"
  local qdrant_host
  local qdrant_port

  qdrant_host="$(get_env_value "QDRANT_HOST")"
  qdrant_host="${qdrant_host:-localhost}"
  qdrant_port="$(get_env_value "QDRANT_PORT")"
  qdrant_port="${qdrant_port:-6333}"

  {
    echo "[qdrant] checking ${qdrant_host}:${qdrant_port}..."

    if wait_for_tcp "${qdrant_host}" "${qdrant_port}" "qdrant" 1; then
      echo "[qdrant] already running."
      return
    fi

    echo "[qdrant] starting Docker container with: ${QDRANT_START_CMD}"
    if ${QDRANT_START_CMD}; then
      wait_for_tcp "${qdrant_host}" "${qdrant_port}" "qdrant" 30 || true
      return
    fi

    echo "[qdrant] regular docker access unavailable or start failed, trying sudo -n..."
    if ${QDRANT_START_SUDO_CMD}; then
      wait_for_tcp "${qdrant_host}" "${qdrant_port}" "qdrant" 30 || true
      return
    fi

    echo "[qdrant] failed to start automatically."
    echo "[qdrant] if this machine requires sudo for docker, please run manually:"
    echo "  sudo docker start ${QDRANT_CONTAINER_NAME}"
    echo "[qdrant] backend will start, but vector/history APIs will fail until Qdrant is reachable."
  } 2>&1 | tee -a "${logfile}"
}

start_judge0_if_possible() {
  local logfile="$1"

  {
    echo "[judge0] working dir: ${JUDGE0_DIR}"
    echo "[judge0] preserving proxy env for outbound access; NO_PROXY=${LOCAL_NO_PROXY}"
    echo "[judge0] checking docker access..."

    if cd "${JUDGE0_DIR}" && docker compose ps >/dev/null 2>&1; then
      echo "[judge0] docker access OK, starting Judge0 with: ${JUDGE0_COMPOSE_CMD}"
      if ${JUDGE0_COMPOSE_CMD}; then
        echo "[judge0] Judge0 startup command sent successfully."
      else
        echo "[judge0] docker compose up failed. Please check Docker service and Judge0 compose logs."
      fi
      return
    fi

    echo "[judge0] regular docker access is unavailable, trying sudo -n..."
    if cd "${JUDGE0_DIR}" && sudo -n docker compose ps >/dev/null 2>&1; then
      echo "[judge0] sudo -n docker access OK, starting Judge0 with: ${JUDGE0_COMPOSE_SUDO_CMD}"
      if ${JUDGE0_COMPOSE_SUDO_CMD}; then
        echo "[judge0] Judge0 startup command sent successfully via sudo -n."
      else
        echo "[judge0] sudo -n docker compose up failed. Please check Docker service and Judge0 compose logs."
      fi
      return
    fi

    echo "[judge0] docker access is unavailable for the current user."
    echo "[judge0] if this machine requires sudo for docker, please run manually:"
    echo "  cd ${JUDGE0_DIR}"
    echo "  sudo docker compose up -d"
    echo "[judge0] the rest of the stack will continue starting."
  } 2>&1 | tee -a "${logfile}"
}

log_ports_hint() {
  cat <<EOF

鏈嶅姟鍚姩鍚庡缓璁鏌ワ細
  ss -lntp | grep ${BACKEND_PORT}
  ss -lntp | grep ${FRONTEND_PORT}
  env | grep -Ei '(^no_proxy=|^NO_PROXY=|^http_proxy=|^https_proxy=)'

鏃ュ織鐩綍锛?  ${LOG_DIR}
  鏈€鏂版棩蹇楄蒋閾炬帴锛?{LOG_ROOT}/latest

甯哥敤鏌ョ湅鍛戒护锛?  tail -f ${LOG_ROOT}/latest/backend.log
  tail -f ${LOG_ROOT}/latest/frontend.log
  tail -f ${LOG_ROOT}/latest/mcp_search.log
  tail -f ${LOG_ROOT}/latest/mcp_scrape.log
  tail -f ${LOG_ROOT}/latest/qdrant.log
  tail -f ${LOG_ROOT}/latest/livekit.log
  tail -f ${LOG_ROOT}/latest/judge0.log

閲嶆柊杩涘叆 tmux锛?  tmux attach -t ${SESSION_NAME}

鏌ョ湅绐楀彛锛?  tmux list-windows -t ${SESSION_NAME}

缁撴潫鏁村鏈嶅姟锛?  tmux kill-session -t ${SESSION_NAME}
EOF
}

main() {
  ensure_tmux
  ensure_conda
  ensure_dirs
  prepare_log_dir
  apply_proxy_env

  if session_exists; then
    log "tmux 浼氳瘽 ${SESSION_NAME} 宸插瓨鍦紝涓嶉噸澶嶅惎鍔ㄣ€?
    log "濡傛灉鍒氳皟鏁翠簡浠ｇ悊鎴?NO_PROXY锛岃鍏堟墽琛?stop.sh 鍐嶉噸鏂?start.sh锛岃鏂扮幆澧冨彉閲忕敓鏁堛€?
    log "杩涘叆浼氳瘽: tmux attach -t ${SESSION_NAME}"
    exit 0
  fi

  log "鍒涘缓 tmux 浼氳瘽: ${SESSION_NAME}"
  tmux new-session -d -s "${SESSION_NAME}" -n "shell" -c "${PROJECT_DIR}"
  sync_tmux_proxy_env

  # 绐楀彛閫€鍑哄悗淇濈暀锛屾柟渚跨湅鎶ラ敊
  tmux set-option -t "${SESSION_NAME}" remain-on-exit on

  # 澧炲ぇ tmux 鍘嗗彶缂撳啿鍖?  tmux set-option -t "${SESSION_NAME}" history-limit "${TMUX_HISTORY_LIMIT}"

  log "灏濊瘯鍚姩 Judge0"
  start_judge0_if_possible "${LOG_DIR}/judge0.log"

  log "鍚姩 Qdrant"
  start_qdrant_if_possible "${LOG_DIR}/qdrant.log"

  log "鍚姩 MCP search"
  make_window "mcp_search" "${PROJECT_DIR}" \
    "${MCP_SEARCH_CMD}" \
    "${LOG_DIR}/mcp_search.log"

  log "鍚姩 MCP web_scrape"
  make_window "mcp_scrape" "${PROJECT_DIR}" \
    "${MCP_SCRAPE_CMD}" \
    "${LOG_DIR}/mcp_scrape.log"

  log "鍚姩 backend"
  make_window "backend" "${PROJECT_DIR}" \
    "${BACKEND_CMD}" \
    "${LOG_DIR}/backend.log"

  log "鍚姩 livekit"
  make_window "livekit" "${PROJECT_DIR}" \
    "${LIVEKIT_CMD}" \
    "${LOG_DIR}/livekit.log"

  log "鍚姩 frontend"
  make_window "frontend" "${FRONTEND_DIR}" \
    "${FRONTEND_CMD}" \
    "${LOG_DIR}/frontend.log"

  # 鍒犻櫎鍒濆 shell 绐楀彛
  tmux kill-window -t "${SESSION_NAME}:shell" 2>/dev/null || true

  log "鍏ㄩ儴鍚姩鍛戒护宸插彂閫佸埌 tmux銆?
  log_ports_hint
}

main "$@"

