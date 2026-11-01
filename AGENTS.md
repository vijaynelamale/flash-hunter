# AGENTS.md — Cross-Development & Target Hardware Guardrails

## 1. Dual-Environment Rules (CRITICAL FOR AGENT EXECUTION)
- **Development Host (Current Machine running IBM Bob):** You are developing and running tests on a host workstation/laptop, NOT on the target Android board.
  - NEVER execute `termux-*` commands, `pkg install`, or live `adb shell` system modifications directly on this development machine.
  - All `pytest` runs on this machine MUST use mocked ADB/`uiautomator2` fixtures, mocked LLM responses, and local HTML fixtures (`DRY_RUN=true`).
- **Deployment Target (Production Runtime):** Xiaomi Mi TV Motherboard (Amlogic ARM64 SoC, 2GB physical RAM, eMMC storage) running Headless Android + Native Termux.
  - Target runtime RSS memory MUST stay strictly under 200MB.

## 2. Banned Dependencies
- NEVER add `playwright`, `selenium`, `puppeteer`, `pandas`, `numpy`, `scipy`, or heavy server daemons (`redis-server`, `postgres`).

## 3. Mandatory Tech Stack & Cross-Platform Fallbacks
- **Async Runtime:** `asyncio` with optional `uvloop` (`try: import uvloop` with standard `asyncio` fallback for cross-OS compatibility).
- **HTTP & WAF Bypass Transport:** Primary `curl_cffi` (`impersonate="chrome124"`), wrapped in a transport adapter that automatically falls back to `httpx[http2]` with a custom Chrome cipher `ssl.SSLContext` if native CFFI wheels are unavailable on a given architecture.
- **HTML Parsing:** `selectolax` (with `beautifulsoup4` + `lxml` fallback only if `selectolax` C-extension is missing).
- **Database & State:** `aiosqlite` (SQLite3 in `WAL` mode, `synchronous=NORMAL`, `temp_store=MEMORY`).
- **Deal Stream Ingestion:** `telethon` for Telegram deal channels + jittered async HTTP category polling.
- **Cloud LLM Verification:** `google-genai` SDK (`gemini-2.5-flash` with Pydantic Structured Outputs) + `httpx` fallback for Groq (`llama-3.3-70b-versatile`).
- **Android Checkout Automation:** `uiautomator2` connecting to a configurable `ADB_SERIAL` (`127.0.0.1:5555` when running on-board in Termux, or `<MI_TV_LAN_IP>:5555` when testing remotely over LAN from the dev machine).