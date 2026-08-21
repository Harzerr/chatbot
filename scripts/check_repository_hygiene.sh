#!/usr/bin/env bash
set -Eeuo pipefail

MAX_TRACKED_FILE_BYTES="${MAX_TRACKED_FILE_BYTES:-10485760}"
FORBIDDEN_PATH_PATTERN='(^|/)(node_modules|build|dist|__pycache__)(/|$)|^(delete|qdrant_storage([^/]*|/.*)|\.qdrant[^/]*(/.*)?|\.local_redis(/.*)?|docs(/.*)?|reports(/.*)?|logs(/.*)?|tools(/.*)?|uploads(/.*)?|assets(/.*)?|venv_py37_backup(/.*)?|api_test_smith(/.*)?|\.tmp_.*)$|\.(db|sqlite|sqlite3|log|zip|tar|tar\.gz|tgz|pdf)$'

forbidden_files="$(git ls-files | grep -E "${FORBIDDEN_PATH_PATTERN}" || true)"
if [[ -n "${forbidden_files}" ]]; then
  echo "Repository hygiene failed: runtime or generated files are tracked:" >&2
  printf '%s\n' "${forbidden_files}" >&2
  exit 1
fi

large_files=()
while IFS= read -r -d '' file; do
  [[ -f "${file}" ]] || continue
  size="$(stat -c '%s' -- "${file}")"
  if (( size > MAX_TRACKED_FILE_BYTES )); then
    large_files+=("${size} ${file}")
  fi
done < <(git ls-files -z)

if (( ${#large_files[@]} > 0 )); then
  echo "Repository hygiene failed: tracked files exceed ${MAX_TRACKED_FILE_BYTES} bytes:" >&2
  printf '%s\n' "${large_files[@]}" >&2
  exit 1
fi

echo "Repository hygiene passed."
