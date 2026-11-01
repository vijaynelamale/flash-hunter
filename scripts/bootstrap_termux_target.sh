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

# Detect Android API level and export resource-friendly compiler flags for 2GB RAM ARM
export ANDROID_API_LEVEL="${ANDROID_API_LEVEL:-24}"
export CARGO_BUILD_JOBS=1
export RUSTFLAGS="-C opt-level=1 -C debuginfo=0"

# Clean up old build caches to free storage on eMMC
echo "[+] Cleaning temporary caches to preserve disk space..."
rm -rf "$HOME/.cargo_target" "$HOME/flash-hunter/.cargo_target" "$HOME/.cache/pip/wheels" 2>/dev/null || true
pkg clean || true

echo "[+] Installing build headers and image libraries for Pillow & Cryptography..."
pkg install -y python python-pip git rust clang binutils libxml2 libxslt libffi openssl sqlite android-tools make pkg-config \
    libjpeg-turbo libpng freetype libwebp openjpeg

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
pip install --upgrade pip setuptools wheel maturin pybind11

export ANDROID_API_LEVEL=24

# Install dependencies
if [ -f "requirements.txt" ]; then
    echo "[+] Installing requirements in virtual environment..."
    pip install --prefer-binary -r requirements.txt || {
        echo "[!] Fallback install with single job..."
        pip install --no-build-isolation -r requirements.txt
    }
fi

mkdir -p data logs

echo "[+] Target bootstrap complete! Ready to start flash-hunter watchdog."
