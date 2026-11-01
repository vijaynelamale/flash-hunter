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

# Detect Android API level and export for Rust/maturin builds
export ANDROID_API_LEVEL="${ANDROID_API_LEVEL:-24}"
export CARGO_BUILD_TARGET_DIR="${PROJECT_DIR:-$HOME/flash-hunter}/.cargo_target"

echo "[+] Installing core build tools and pre-compiled Termux Python wheels..."
pkg install -y python python-pip git rust clang binutils libxml2 libxslt libffi openssl sqlite android-tools make pkg-config \
    python-pydantic python-pydantic-core python-pydantic-settings python-cryptography python-lxml python-pillow python-yaml python-httpx || {
    echo "[!] Some pre-compiled packages were not in pkg repo; installing base packages..."
    pkg install -y python python-pip git rust clang binutils libxml2 libxslt libffi openssl sqlite android-tools make pkg-config
}

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

# Re-create virtual environment with system site packages to leverage native Termux wheels
if [ ! -d ".venv" ]; then
    echo "[+] Creating dedicated target virtual environment with system site packages..."
    python -m venv --system-site-packages .venv
fi

# Activate venv
source .venv/bin/activate
pip install --upgrade pip setuptools wheel maturin

export ANDROID_API_LEVEL=24

# Install dependencies
if [ -f "requirements.txt" ]; then
    echo "[+] Installing remaining requirements in virtual environment..."
    pip install --prefer-binary -r requirements.txt || {
        echo "[!] Standard install had failures; installing with --no-build-isolation..."
        pip install --no-build-isolation --prefer-binary -r requirements.txt
    }
fi

mkdir -p data logs

echo "[+] Target bootstrap complete! Ready to start flash-hunter watchdog."
