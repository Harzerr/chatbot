#!/usr/bin/env bash
set -euo pipefail

SESSION_NAME="${SESSION_NAME:-chatbot_stack}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${PROJECT_DIR:-${SCRIPT_DIR}}"
JUDGE0_DIR="${JUDGE0_DIR:-${PROJECT_DIR}/tools/judge0-v1.13.1}"
JUDGE0_STOP_CMD="${JUDGE0_STOP_CMD:-docker compose down}"
JUDGE0_STOP_SUDO_CMD="${JUDGE0_STOP_SUDO_CMD:-sudo -n docker compose down}"
LOCAL_NO_PROXY="localhost,127.0.0.1,::1"

stop_judge0_if_possible() {
  if [[ ! -d "${JUDGE0_DIR}" ]]; then
    echo "Judge0 目录不存在，跳过: ${JUDGE0_DIR}"
    return
  fi

  unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY
  export NO_PROXY="${LOCAL_NO_PROXY}"
  export no_proxy="${LOCAL_NO_PROXY}"

  if cd "${JUDGE0_DIR}" && docker compose ps >/dev/null 2>&1; then
    echo "尝试停止 Judge0..."
    if ${JUDGE0_STOP_CMD}; then
      echo "已停止 Judge0"
    else
      echo "Judge0 停止失败，请手动检查 Docker 和 compose 状态"
    fi
    return
  fi

  if cd "${JUDGE0_DIR}" && sudo -n docker compose ps >/dev/null 2>&1; then
    echo "尝试通过 sudo -n 停止 Judge0..."
    if ${JUDGE0_STOP_SUDO_CMD}; then
      echo "已通过 sudo -n 停止 Judge0"
    else
      echo "Judge0 停止失败，请手动检查 Docker 和 compose 状态"
    fi
    return
  fi

  echo "当前用户没有 Docker 权限，未自动停止 Judge0。"
  echo "如需手动停止，请执行："
  echo "  cd ${JUDGE0_DIR}"
  echo "  sudo docker compose down"
}

if tmux has-session -t "${SESSION_NAME}" 2>/dev/null; then
  tmux kill-session -t "${SESSION_NAME}"
  echo "已停止 tmux 会话: ${SESSION_NAME}"
else
  echo "tmux 会话不存在: ${SESSION_NAME}"
fi

stop_judge0_if_possible
