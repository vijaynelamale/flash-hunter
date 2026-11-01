#!/data/data/com.termux/files/usr/bin/bash
# ==============================================================================
# Flash-Hunter Target Watchdog & Auto-Restart Runner
# Runs inside Termux on Xiaomi Mi TV Motherboard (2GB RAM constraint)
# ==============================================================================

set -uo pipefail

PROJECT_DIR="${HOME}/flash-hunter"
cd "${PROJECT_DIR}" || exit 1

# Max allowed RSS memory for flash-hunter process in KB (190MB limit for safety)
MAX_RSS_KB=194560
LOG_FILE="${PROJECT_DIR}/logs/hunter_watchdog.log"
mkdir -p "${PROJECT_DIR}/logs" "${PROJECT_DIR}/data"

# Acquire Termux wake lock if available
if command -v termux-wake-lock >/dev/null 2>&1; then
    termux-wake-lock
fi

source "${PROJECT_DIR}/.venv/bin/activate"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting Flash-Hunter Watchdog Supervisor..." >> "${LOG_FILE}"

while true; do
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Launching Flash-Hunter Core Process..." | tee -a "${LOG_FILE}"
    
    "${PROJECT_DIR}/.venv/bin/python" -u src/main.py >> "${LOG_FILE}" 2>&1 &
    HUNTER_PID=$!
    
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Flash-Hunter started with PID: ${HUNTER_PID}" | tee -a "${LOG_FILE}"
    
    # Internal Watchdog Loop: monitor PID and RSS memory
    while kill -0 "${HUNTER_PID}" 2>/dev/null; do
        sleep 5
        
        # Check RSS memory usage in KB
        if [ -f "/proc/${HUNTER_PID}/statm" ]; then
            PAGES=$(awk '{print $2}' "/proc/${HUNTER_PID}/statm" 2>/dev/null || echo 0)
            PAGE_SIZE_KB=$(getconf PAGESIZE 2>/dev/null || echo 4096)
            PAGE_SIZE_KB=$((PAGE_SIZE_KB / 1024))
            RSS_KB=$((PAGES * PAGE_SIZE_KB))
            
            if [ "${RSS_KB}" -gt "${MAX_RSS_KB}" ]; then
                echo "[$(date '+%Y-%m-%d %H:%M:%S')] WARNING: Memory threshold exceeded (${RSS_KB} KB > ${MAX_RSS_KB} KB). Restarting PID ${HUNTER_PID}..." | tee -a "${LOG_FILE}"
                kill -15 "${HUNTER_PID}" 2>/dev/null || true
                sleep 3
                kill -9 "${HUNTER_PID}" 2>/dev/null || true
                break
            fi
        fi
    done
    
    wait "${HUNTER_PID}" 2>/dev/null || true
    EXIT_CODE=$?
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Flash-Hunter process exited with code ${EXIT_CODE}. Restarting in 3s..." | tee -a "${LOG_FILE}"
    sleep 3
done
