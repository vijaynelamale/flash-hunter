#!/data/data/com.termux/files/usr/bin/bash
# ==============================================================================
# Flash-Hunter Target Board Bootstrapper (Mi TV Native Termux ARM64)
# RUN ONLY ON THE TARGET ANDROID BOARD, NEVER ON DEV HOST MACHINE.
# ==============================================================================

set -euo pipefail

echo "[+] Bootstrapping Flash-Hunter on Native Termux ARM64..."

# 1. Acquire Termux Wake-Lock to prevent CPU throttling
if command -v termux-wake-lock >/dev/null 2>&1; then
    echo "[+] Acquiring termux-wake-lock..."
    termux-wake-lock
else
    echo "[!] termux-wake-lock not found. Ensure Termux:API is installed."
fi

# 2. Update Termux repositories and install core packages
echo "[+] Updating pkg repositories..."
pkg update -y && pkg upgrade -y

echo "[+] Installing core build tools and dependencies..."
pkg install -y python git rust clang binutils libxml2 libxslt libffi openssl sqlite android-tools

# 3. Optimize ADB daemon & connect to target device
PROJECT_DIR="${HOME}/flash-hunter"
TARGET_ADB="${1:-${ADB_TARGET:-}}"

# Check if ADB_TARGET is in .env
if [ -z "${TARGET_ADB}" ] && [ -f "${PROJECT_DIR}/.env" ]; then
    TARGET_ADB=$(grep -E '^ADB_TARGET=' "${PROJECT_DIR}/.env" | cut -d '=' -f2- | tr -d '"' | tr -d "'" | tr -d ' ' || true)
fi

# Fallback default
TARGET_ADB="${TARGET_ADB:-10.42.0.90:5555}"
echo "[+] Target ADB Device: ${TARGET_ADB}"

echo "[+] Initializing ADB daemon and connecting to ${TARGET_ADB}..."
adb start-server || true
adb connect "${TARGET_ADB}" || true

# 4. Disable Battery Optimization (Doze Mode) for Termux and Shopping Apps on target device
echo "[+] Disabling Android Doze battery optimizations on device ${TARGET_ADB}..."
adb -s "${TARGET_ADB}" shell dumpsys deviceidle whitelist +com.termux || true
adb -s "${TARGET_ADB}" shell dumpsys deviceidle whitelist +in.amazon.mShop.android.shopping || true
adb -s "${TARGET_ADB}" shell dumpsys deviceidle whitelist +com.flipkart.android || true

# 5. Create Python Virtual Environment on Target
PROJECT_DIR="$HOME/flash-hunter"
mkdir -p "$PROJECT_DIR"
cd "$PROJECT_DIR"

if [ ! -d ".venv" ]; then
    echo "[+] Creating dedicated target ARM64 virtual environment..."
    python -m venv .venv
fi

# Activate venv
source .venv/bin/activate
pip install --upgrade pip setuptools wheel

# Install dependencies (will build native C-extensions or use pure python fallbacks)
if [ -f "requirements.txt" ]; then
    echo "[+] Installing requirements on ARM64..."
    pip install -r requirements.txt || {
        echo "[!] Standard install had failures; installing with fallback resilience..."
        pip install --no-build-isolation -r requirements.txt
    }
fi

mkdir -p data logs

echo "[+] Target bootstrap complete! Ready to start flash-hunter watchdog."
