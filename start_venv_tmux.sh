#!/usr/bin/env bash
set -Eeuo pipefail

SESSION_NAME="${SESSION_NAME:-chatbot_stack}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${PROJECT_DIR:-${SCRIPT_DIR}}"
VENV_DIR="${VENV_DIR:-${PROJECT_DIR}/.venv}"
FRONTEND_DIR="${FRONTEND_DIR:-${PROJECT_DIR}/frontend}"
LOG_DIR="${LOG_DIR:-${PROJECT_DIR}/logs/tmux}"

BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"

MCP_SEARCH_CMD="${MCP_SEARCH_CMD:-python -m app.mcp_server.search_server}"
MCP_SCRAPE_CMD="${MCP_SCRAPE_CMD:-python -m app.mcp_server.web_scrapping_server}"
BACKEND_CMD="${BACKEND_CMD:-python app.py}"
RESUME_WORKER_CMD="${RESUME_WORKER_CMD:-python -m app.workers.resume_worker}"
FRONTEND_CMD="${FRONTEND_CMD:-npm start}"

LOCAL_NO_PROXY="${LOCAL_NO_PROXY:-localhost,127.0.0.1,::1}"

log() {
  echo "[start_venv_tmux] $*"
}

ensure_ready() {
  command -v tmux >/dev/null 2>&1 || {
    echo "tmux 未安装，请先执行: sudo apt update && sudo apt install -y tmux"
    exit 1
  }

  [[ -x "${VENV_DIR}/bin/python" ]] || {
    echo "找不到 Python 虚拟环境: ${VENV_DIR}"
    echo "如需创建，请执行: python3 -m venv ${VENV_DIR} && source ${VENV_DIR}/bin/activate && pip install -r ${PROJECT_DIR}/requirements.txt"
    exit 1
  }

  [[ -d "${FRONTEND_DIR}" ]] || {
    echo "找不到前端目录: ${FRONTEND_DIR}"
    exit 1
  }

  mkdir -p "${LOG_DIR}"
}

session_exists() {
  tmux has-session -t "${SESSION_NAME}" 2>/dev/null
}

send_window() {
  local window_name="$1"
  local workdir="$2"
  local command="$3"
  local logfile="$4"

  tmux new-window -t "${SESSION_NAME}" -n "${window_name}" -c "${workdir}"
  tmux send-keys -t "${SESSION_NAME}:${window_name}" \
    "unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY && \
export NO_PROXY='${LOCAL_NO_PROXY}' no_proxy='${LOCAL_NO_PROXY}' && \
source '${VENV_DIR}/bin/activate' && \
cd '${workdir}' && \
echo '[${window_name}] logging to ${logfile}' && \
(${command}) 2>&1 | tee -a '${logfile}'" C-m
}

wait_for_tcp() {
  local host="$1"
  local port="$2"
  local label="$3"
  local attempts="${4:-30}"

  for ((i = 1; i <= attempts; i++)); do
    if timeout 1 bash -c "cat < /dev/null > /dev/tcp/${host}/${port}" >/dev/null 2>&1; then
      log "${label} ready at ${host}:${port}"
      return 0
    fi
    sleep 1
  done

  log "${label} not reachable at ${host}:${port} after ${attempts}s"
  return 1
}

main() {
  ensure_ready

  if session_exists; then
    log "tmux 会话已存在: ${SESSION_NAME}"
    log "进入会话: tmux attach -t ${SESSION_NAME}"
    log "如需重启: tmux kill-session -t ${SESSION_NAME} && ${PROJECT_DIR}/start_venv_tmux.sh"
    exit 0
  fi

  log "创建 tmux 会话: ${SESSION_NAME}"
  tmux new-session -d -s "${SESSION_NAME}" -n shell -c "${PROJECT_DIR}"
  tmux set-option -t "${SESSION_NAME}" remain-on-exit on
  tmux set-option -t "${SESSION_NAME}" history-limit 100000

  send_window "mcp_search" "${PROJECT_DIR}" "${MCP_SEARCH_CMD}" "${LOG_DIR}/mcp_search.log"
  send_window "mcp_scrape" "${PROJECT_DIR}" "${MCP_SCRAPE_CMD}" "${LOG_DIR}/mcp_scrape.log"
  send_window "resume_worker" "${PROJECT_DIR}" "${RESUME_WORKER_CMD}" "${LOG_DIR}/resume_worker.log"

  send_window "backend" "${PROJECT_DIR}" \
    "export UVICORN_HOST='${BACKEND_HOST}' UVICORN_PORT='${BACKEND_PORT}' && ${BACKEND_CMD}" \
    "${LOG_DIR}/backend.log"

  tmux new-window -t "${SESSION_NAME}" -n frontend -c "${FRONTEND_DIR}"
  tmux send-keys -t "${SESSION_NAME}:frontend" \
    "unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY && \
export NO_PROXY='${LOCAL_NO_PROXY}' no_proxy='${LOCAL_NO_PROXY}' && \
cd '${FRONTEND_DIR}' && \
echo '[frontend] logging to ${LOG_DIR}/frontend.log' && \
(PORT='${FRONTEND_PORT}' BROWSER=none ${FRONTEND_CMD}) 2>&1 | tee -a '${LOG_DIR}/frontend.log'" C-m

  tmux kill-window -t "${SESSION_NAME}:shell" 2>/dev/null || true

  wait_for_tcp "127.0.0.1" "6379" redis 30 || true
  wait_for_tcp "${BACKEND_HOST}" "${BACKEND_PORT}" backend 45 || true
  wait_for_tcp "127.0.0.1" "${FRONTEND_PORT}" frontend 45 || true

  cat <<EOF

启动完成。
  前端: http://127.0.0.1:${FRONTEND_PORT}
  后端: http://${BACKEND_HOST}:${BACKEND_PORT}
  tmux: tmux attach -t ${SESSION_NAME}
  日志: ${LOG_DIR}

停止:
  tmux kill-session -t ${SESSION_NAME}
EOF
}

main "$@"
