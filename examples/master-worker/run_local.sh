#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE=""

usage() {
  echo "Usage: $0 [--env-file <path>]"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env-file)
      if [[ $# -lt 2 ]]; then
        usage
        exit 1
      fi
      ENV_FILE="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1"
      usage
      exit 1
      ;;
  esac
done

if [[ -n "${ENV_FILE}" ]]; then
  if [[ ! -f "${ENV_FILE}" ]]; then
    echo "Env file not found: ${ENV_FILE}"
    exit 1
  fi
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
elif [[ -f "${ROOT_DIR}/examples/master-worker/.env.local" ]]; then
  # shellcheck disable=SC1091
  source "${ROOT_DIR}/examples/master-worker/.env.local"
elif [[ -f "${ROOT_DIR}/examples/master-worker/env.local.sample" ]]; then
  # shellcheck disable=SC1091
  source "${ROOT_DIR}/examples/master-worker/env.local.sample"
fi

MASTER_PORT="${MASTER_PORT:-8080}"
WORKER_PORT="${WORKER_PORT:-8081}"
MASTER_FRONTEND_PORT="${MASTER_FRONTEND_PORT:-5174}"
MASTER_HOST="${MASTER_HOST:-127.0.0.1}"
MASTER_FRONTEND_API_PROXY="${MASTER_FRONTEND_API_PROXY:-http://${MASTER_HOST}:${MASTER_PORT}}"

if [[ -d "${ROOT_DIR}/.venv" ]]; then
  # shellcheck disable=SC1091
  source "${ROOT_DIR}/.venv/bin/activate"
fi

cleanup() {
  if [[ -n "${MASTER_PID:-}" ]] && kill -0 "${MASTER_PID}" 2>/dev/null; then
    kill "${MASTER_PID}" 2>/dev/null || true
  fi
  if [[ -n "${WORKER_PID:-}" ]] && kill -0 "${WORKER_PID}" 2>/dev/null; then
    kill "${WORKER_PID}" 2>/dev/null || true
  fi
  if [[ -n "${FRONTEND_PID:-}" ]] && kill -0 "${FRONTEND_PID}" 2>/dev/null; then
    kill "${FRONTEND_PID}" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

echo "Starting master backend on ${MASTER_HOST}:${MASTER_PORT}"
python3 -m uvicorn master_backend.main:app --host "${MASTER_HOST}" --port "${MASTER_PORT}" &
MASTER_PID=$!

echo "Starting worker backend on ${MASTER_HOST}:${WORKER_PORT}"
export DISTRIBUTED_WORKER_ENABLED=true
export MASTER_BASE_URL="http://${MASTER_HOST}:${MASTER_PORT}"
export WORKER_NODE_ID="${WORKER_NODE_ID:-worker-local}"
export WORKER_HOSTNAME="${WORKER_HOSTNAME:-worker-local}"
export WORKER_API_PORT="${WORKER_PORT}"
python3 -m uvicorn worker_backend.main:app --host "${MASTER_HOST}" --port "${WORKER_PORT}" &
WORKER_PID=$!

echo "Starting master frontend on ${MASTER_HOST}:${MASTER_FRONTEND_PORT}"
(
  cd "${ROOT_DIR}/master-frontend"
  VITE_API_PROXY_TARGET="${MASTER_FRONTEND_API_PROXY}" npm run dev -- --host "${MASTER_HOST}" --port "${MASTER_FRONTEND_PORT}"
) &
FRONTEND_PID=$!

echo "Master PID=${MASTER_PID}, Worker PID=${WORKER_PID}, Frontend PID=${FRONTEND_PID}"
echo "Master API: http://${MASTER_HOST}:${MASTER_PORT}/api/master/cluster/status"
echo "Worker API: http://${MASTER_HOST}:${WORKER_PORT}/api/status"
echo "Master Frontend: http://${MASTER_HOST}:${MASTER_FRONTEND_PORT}"

wait "${MASTER_PID}" "${WORKER_PID}" "${FRONTEND_PID}"
