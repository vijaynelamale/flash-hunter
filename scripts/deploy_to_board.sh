#!/usr/bin/env bash
# ==============================================================================
# Flash-Hunter Deployment Script (Runs on Dev Host Machine)
# Synchronizes clean codebase to Xiaomi Mi TV Termux via Rsync over SSH
# ==============================================================================

set -euo pipefail

TARGET_HOST="${1:-192.168.1.50}"
TARGET_PORT="${2:-8022}"
TARGET_USER="${3:-$(whoami)}"
REMOTE_PATH="~/flash-hunter"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "=================================================================="
echo " Deploying Flash-Hunter to Xiaomi Mi TV Board"
echo " Target: ${TARGET_USER}@${TARGET_HOST}:${TARGET_PORT}"
echo " Remote Path: ${REMOTE_PATH}"
echo "=================================================================="

# Ensure rsync is available on host
if ! command -v rsync >/dev/null 2>&1; then
    echo "[-] Error: rsync is required on host development machine."
    exit 1
fi

echo "[+] Syncing codebase (excluding host venvs, DBs, and compiled cache)..."

rsync -avz --delete \
    -e "ssh -p ${TARGET_PORT}" \
    --exclude-from="${PROJECT_ROOT}/.stignore" \
    --exclude=".git" \
    --exclude=".venv" \
    --exclude="venv" \
    --exclude="__pycache__" \
    --exclude="*.pyc" \
    --exclude="*.db" \
    --exclude="*.db-wal" \
    --exclude="*.db-shm" \
    --exclude="logs/*" \
    "${PROJECT_ROOT}/" \
    "${TARGET_USER}@${TARGET_HOST}:${REMOTE_PATH}/"

echo "[+] Deployment synchronization successful!"
echo ""
echo "To run bootstrap on the board (first time only):"
echo "  ssh -p ${TARGET_PORT} ${TARGET_USER}@${TARGET_HOST} 'bash ~/flash-hunter/scripts/bootstrap_termux_target.sh'"
echo ""
echo "To start the autonomous watchdog on the board:"
echo "  ssh -p ${TARGET_PORT} ${TARGET_USER}@${TARGET_HOST} 'nohup bash ~/flash-hunter/scripts/start_hunter_termux.sh > /dev/null 2>&1 &'"
echo "=================================================================="
