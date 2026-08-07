#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
export RESUME_TEST_REDIS_URL="${RESUME_TEST_REDIS_URL:-redis://127.0.0.1:6379/15}"
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"

exec ./.venv/bin/python tests/benchmark_resume_queue.py "$@"
