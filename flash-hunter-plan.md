# Flash-Hunter: Autonomous Flash-Sale Hunter & Auto-Checkout Assistant Plan

## Top-Level Overview
`flash-hunter` is a lightweight, cross-platform, asynchronous flash-sale monitoring and auto-checkout system tailored for Amazon India (`amazon.in`) and Flipkart (`flipkart.com`).
The application is designed to run in two topologies:
1. **On-Board Standalone Mode:** On a resource-constrained ARM64 Android board (Xiaomi Mi TV motherboard running headless Android + Termux with <200MB RSS footprint).
2. **Remote LAN Controller Mode / Host Dev Mode:** Running on a host development laptop controlling the board over Wi-Fi/LAN ADB or mocked 100% offline with zero physical dependencies for testing.

The system ingests deal alerts from Telegram broadcast channels and category pollers, unshortens and normalizes affiliate links, parses live product pages with WAF-resilient transports, filters deals via a sub-millisecond rule engine, performs structured verification via Gemini 2.5 Flash (with Groq fallback), enforces circuit breaker spend caps, triggers automated checkout via Android deep links & `uiautomator2`, and supports interactive 2-way Telegram bot management.

---

## Architecture & Sub-Tasks

### Sub-Task 1: Project Scaffolding & Configuration Architecture
- **Intent:** Set up dependencies, configuration definitions, deployment scripts, and ignore rules adhering to dual-environment constraints.
- **Expected Outcomes:**
  - `requirements.txt` containing pinned cross-platform libraries without banned dependencies.
  - `.env.example` defining all operational parameters (API keys, Telegram tokens, ADB target, budget caps, execution mode).
  - `.stignore` ensuring `.venv`, SQLite databases, logs, and `__pycache__` are excluded from Syncthing sync.
  - `config/targets.yaml` declaring category poll URLs, target keywords, maximum trigger prices, discount thresholds, and negative keyword lists.
  - `src/config_loader.py` implementing Pydantic v2 settings validation with defaults and schema validation.
  - `scripts/bootstrap_termux_target.sh`, `scripts/start_hunter_termux.sh`, and `scripts/deploy_to_board.sh` for ARM64 deployment and watchdog execution.
- **Status:** `[ ] pending`

### Sub-Task 2: Resilient Transport & Parsing Pipeline
- **Intent:** Build high-performance, WAF-resistant HTTP fetcher and DOM extraction logic with native and pure-Python fallbacks.
- **Expected Outcomes:**
  - `src/transport/http_client.py`: Dual-transport adapter prioritizing `curl_cffi` (impersonating `chrome124`) with automatic fallback to `httpx[http2]` + custom Chrome cipher `ssl.SSLContext`.
  - `src/scraper/product_fetcher.py`: Fast `selectolax` parser (with `bs4`/`lxml` fallback) extracting price, title, stock status, seller rating, and product ID (ASIN / FSN) for Amazon India and Flipkart.
  - `tests/fixtures/amazon_product_sample.html` & `tests/fixtures/flipkart_product_sample.html`: Real-world mock HTML snippets.
  - `tests/test_scraper_parsers.py`: Unit tests validating extraction accuracy, handling out-of-stock items, price changes, and malformed HTML.
- **Status:** `[ ] pending`

### Sub-Task 3: State Storage, Dedup Ledger & Circuit Breaker Safety
- **Intent:** Provide zero-overhead persistent state tracking, deduplication, and safety spend controls.
- **Expected Outcomes:**
  - `src/db/state_store.py`: `aiosqlite` SQLite3 engine running in WAL mode (`synchronous=NORMAL`, `temp_store=MEMORY`) with tables for seen deals, order ledger, and audit log.
  - `src/safety/circuit_breaker.py`: Concurrency-safe spend enforcement (daily spend limit, single-item max price, post-order kill switch, cooldown timers) protected by `asyncio.Lock`.
  - `tests/test_circuit_breaker.py`: Tests verifying limits are strictly enforced and concurrent deal races cannot breach budgets.
- **Status:** `[ ] pending`

### Sub-Task 4: Deal Ingestion & Filtering Engine
- **Intent:** Ingest stream alerts in real time from Telegram and periodic category pollers, unshortening URLs and filtering junk deals in sub-millisecond execution.
- **Expected Outcomes:**
  - `src/ingestion/telegram_stream.py`: Telethon client listening to deal channels, extracting deal URLs via regex, and asynchronously unshortening affiliate redirects (amzn.to, fkrt.it, bit.ly, etc.).
  - `src/ingestion/category_poller.py`: Jittered async poller for target category deals.
  - `src/filter/rule_engine.py`: High-throughput filter evaluating price thresholds, discount percentage, stock availability, and negative keywords (e.g., refurbished, renewed, cover, skin, back case).
  - `tests/test_rule_engine.py`: Unit tests verifying pass/fail conditions for pricing, discount calculations, and keyword blacklists.
- **Status:** `[ ] pending`

### Sub-Task 5: Cloud LLM Verification with Structured Outputs
- **Intent:** Provide high-precision verification using Gemini 2.5 Flash with Groq fallback to eliminate false positives and affiliate bait before checkout.
- **Expected Outcomes:**
  - `src/intelligence/llm_validator.py`: `google-genai` SDK implementation with Pydantic structured output model (`DealVerificationResult`: `is_authentic_deal`, `confidence_score`, `model_name`, `rationale`), and an `httpx` Groq fallback (`llama-3.3-70b-versatile`).
  - `tests/test_llm_validator.py`: Unit tests with mocked API responses validating schema parsing, error recovery, and fallback switching.
- **Status:** `[ ] pending`

### Sub-Task 6: Modular Checkout Drivers (ADB, LAN Webhook, Mock)
- **Intent:** Implement pluggable checkout drivers for on-board Termux execution, remote host control, and offline host testing.
- **Expected Outcomes:**
  - `src/checkout/base.py`: Abstract `CheckoutDriver` base class.
  - `src/checkout/mock_checkout.py`: Simulated driver for offline development and `DRY_RUN` mode.
  - `src/checkout/adb_checkout.py`: `uiautomator2` driver opening Android deep links (`amzn://...`, `flipkart://...`), navigating Buy Now, selecting payment method (e.g. COD / pre-selected UPI), and handling UI prompts.
  - `src/checkout/lan_webhook.py`: Secure HMAC-signed HTTP webhook client for offloading checkout to an external device.
  - `tests/test_adb_checkout_mocked.py`: Unit tests validating ADB deep linking, intent construction, and UI automation flow using mocked device fixtures.
- **Status:** `[ ] pending`

### Sub-Task 7: 2-Way Telegram Notification & Remote Control Bot
- **Intent:** Provide real-time alerts with 1-tap manual buy triggers and full remote operational control.
- **Expected Outcomes:**
  - `src/notifier/telegram_bot.py`: Telegram Bot handler sending formatted markdown alerts, photo cards, inline checkout confirmation buttons, and supporting commands (`/status`, `/mode`, `/pause`, `/resume`, `/kill`, `/budget`).
- **Status:** `[ ] pending`

### Sub-Task 8: Orchestrator, Main Entrypoint & End-to-End Verification
- **Intent:** Wire all subsystems into `src/main.py` with graceful shutdown signal handling, complete documentation, and 100% test pass rate.
- **Expected Outcomes:**
  - `src/main.py`: Main async event loop coordinating ingestion, scraping, filtering, verification, checkout, notifications, and watchdog health check.
  - `README.md`: Comprehensive guide covering architecture, host development, Termux on-board deployment, ADB configuration, and troubleshooting.
  - Complete `pytest` test suite passing on the host development machine without live ADB or external dependencies.
- **Status:** `[ ] pending`
