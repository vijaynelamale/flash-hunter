# Flash-Hunter: Autonomous Flash-Sale Hunter & Auto-Checkout Assistant

Autonomous, high-speed flash-sale detection, LLM deal verification, and automated zero-OTP checkout assistant for **Amazon India (`amazon.in`)** and **Flipkart (`flipkart.com`)**.

Engineered for **cross-platform development** on Host Dev Workstations and deployment on resource-constrained **ARM64 edge devices (Xiaomi Mi TV motherboard, 2GB RAM, Native Termux with <200MB RSS footprint)**.

---

## Key Architectural Features

- **Dual-Environment Architecture:**
  - **Dev Host Offline Mode:** Develop, lint, and run 100% offline mocked unit tests with zero Android/ADB hardware dependencies (`DRY_RUN=true`).
  - **On-Board Standalone Mode:** Runs inside Native Termux on the Mi TV motherboard, directly driving local ADB (`127.0.0.1:5555`).
  - **Remote LAN Controller Mode:** Run from your development laptop while controlling the Mi TV board over Wi-Fi/LAN ADB (`<MI_TV_IP>:5555`).
- **Resilient Transport & Anti-WAF:**
  - Primary `curl_cffi` with `chrome124` browser TLS fingerprint impersonation.
  - Automatic fallback to `httpx[http2]` configured with Chrome SSL cipher suites.
- **Fast HTML Parsing:**
  - Sub-millisecond DOM parsing via `selectolax` (with `BeautifulSoup4` + `lxml` fallback).
- **Sub-Millisecond Fast Rule Engine:**
  - Evaluates user expectations (`natural_language_spec`), price caps, discount percentages, and negative keywords (blocking accessories/traps).
  - Global `crazy_deal_override` (e.g., >=90% discount under ₹1,000 across all streams).
- **Cloud LLM Verification:**
  - `gemini-2.5-flash` with strict Pydantic Structured Outputs.
  - Automatic fallback to Groq `llama-3.3-70b-versatile` and offline heuristics.
- **Zero-OTP Automated Checkout & Price Guard:**
  - Supports **Amazon Pay Balance**, **Flipkart Gift Card / Wallet**, and **COD / Pay on Delivery**.
  - **NPCI UPI Excluded:** Avoids Android `FLAG_SECURE` screen capture blocks.
  - **Mandatory Final Price Guard:** Inspects the UI XML hierarchy right before final confirmation; immediately aborts (`d.press("home")`) and alerts if flash prices surged or expired mid-checkout.
- **Financial Safety Circuit Breaker:**
  - Daily spend limits, single-item price caps, post-order kill switches, and concurrency race-condition locks.
- **2-Way Telegram Control:**
  - Real-time Markdown alerts and interactive commands (`/status`, `/pause`, `/resume`, `/kill`, `/reset_kill`).

---

## Repository Structure

```text
flash-hunter/
├── AGENTS.md                      # Target hardware constraints & guardrails
├── README.md                      # Documentation & deployment guide
├── requirements.txt               # Pinned cross-platform dependencies
├── pytest.ini                     # Pytest runner configuration
├── .env.example                   # Environment configuration template
├── .stignore                      # Syncthing ignore patterns (.venv, *.db, cache)
├── config/
│   └── targets.yaml               # Target categories, NL specs & crazy deal rules
├── scripts/
│   ├── bootstrap_termux_target.sh # Target Termux setup (run ONLY on Mi TV)
│   ├── start_hunter_termux.sh     # Target watchdog supervisor (<200MB RSS)
│   └── deploy_to_board.sh         # Host machine Rsync/SSH deployment script
├── src/
│   ├── __init__.py
│   ├── main.py                    # Asyncio orchestrator & deal worker pool
│   ├── config_loader.py           # Pydantic v2 settings & YAML target loader
│   ├── db/
│   │   └── state_store.py         # aiosqlite WAL store (dedup, orders, audit)
│   ├── transport/
│   │   └── http_client.py         # curl_cffi + httpx[http2] resilient transport
│   ├── ingestion/
│   │   ├── telegram_stream.py     # Telethon listener & URL unshortener
│   │   └── category_poller.py     # Jittered async category poller
│   ├── scraper/
│   │   └── product_fetcher.py     # selectolax parser (Amazon ASIN / Flipkart PID)
│   ├── filter/
│   │   └── rule_engine.py         # Sub-millisecond filter & crazy deal evaluator
│   ├── intelligence/
│   │   └── llm_validator.py       # Gemini 2.5 Flash + Groq fallback
│   ├── checkout/
│   │   ├── base.py                # Abstract CheckoutDriver interface
│   │   ├── adb_checkout.py        # uiautomator2 + deep link zero-OTP checkout
│   │   ├── lan_webhook.py         # Signed HMAC-SHA256 webhook driver
│   │   └── mock_checkout.py       # Mock driver for host offline testing
│   ├── safety/
│   │   └── circuit_breaker.py     # Budget caps, race locks, & kill switches
│   └── notifier/
│       └── telegram_bot.py        # 2-way Telegram notification & control bot
└── tests/
    ├── fixtures/
    │   ├── amazon_product_sample.html
    │   └── flipkart_product_sample.html
    ├── test_rule_engine.py
    ├── test_scraper_parsers.py
    ├── test_llm_validator.py
    ├── test_adb_checkout_mocked.py
    └── test_circuit_breaker.py
```

---

## Local Development & Testing (Host Machine)

### 1. Setup Virtual Environment
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure Environment
```bash
cp .env.example .env
# Edit .env with your Telegram, Gemini/Groq, and target configurations
```

### 3. Run Unit Tests (100% Mocked / Offline)
```bash
pytest -v
```

---

## Deployment to Xiaomi Mi TV Board (ARM64 Termux)

### 1. Synchronize Code to Board via SSH / Rsync
From your host machine:
```bash
bash scripts/deploy_to_board.sh <MI_TV_IP> 8022 <TERMUX_USER>
```

### 2. Bootstrap Target Environment (First Time Only)
On the Mi TV Termux terminal:
```bash
bash ~/flash-hunter/scripts/bootstrap_termux_target.sh
```

### 3. Start Watchdog Supervisor
On the Mi TV Termux terminal:
```bash
nohup bash ~/flash-hunter/scripts/start_hunter_termux.sh > /dev/null 2>&1 &
```
