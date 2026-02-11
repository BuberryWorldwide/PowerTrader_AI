# Changelog: Robinhood → Coinbase Advanced Trade API Migration

This documents every change made to fork PowerTrader_AI from Robinhood Crypto Trading API to Coinbase Advanced Trade API. The AI logic (kNN pattern matching), DCA strategy, trailing profit margin system, and KuCoin candle data source are all unchanged.

---

## Files Modified

| File | Lines Changed | Summary |
|------|--------------|---------|
| `requirements.txt` | 1 removed, 1 added | Swap `PyNaCl` for `coinbase-advanced-py` |
| `pt_trader.py` | ~592 lines (net -235) | Rewrite broker class from Robinhood HTTP+ED25519 to Coinbase SDK |
| `pt_thinker.py` | ~111 lines (net -44) | Replace price data class from Robinhood to Coinbase |
| `pt_hub.py` | ~389 lines (net -304) | Replace credential wizard (simpler — no key generation step) |
| `pt_trainer.py` | ~20 lines added | Training progress logging (unrelated to migration) |
| `README.md` | Full rewrite | Updated for Coinbase setup and usage |

---

## 1. requirements.txt

```diff
-PyNaCl
+coinbase-advanced-py
```

- **Removed**: `PyNaCl` — Robinhood's ED25519 request signing library
- **Added**: `coinbase-advanced-py` — Official Coinbase SDK (handles JWT auth internally)
- **Kept**: `requests`, `psutil`, `matplotlib`, `colorama`, `cryptography`, `kucoin-python`

---

## 2. pt_trader.py — Core Trading Class (`CryptoAPITrading`)

### 2a. Imports

```diff
-import base64
-import requests
-from nacl.signing import SigningKey
-from cryptography.hazmat.primitives.asymmetric import ed25519
-from cryptography.hazmat.primitives import serialization
+from coinbase.rest import RESTClient
```

### 2b. Credential Loading

```diff
-with open('r_key.txt', 'r', encoding='utf-8') as f:
-    API_KEY = (f.read() or "").strip()
-with open('r_secret.txt', 'r', encoding='utf-8') as f:
-    BASE64_PRIVATE_KEY = (f.read() or "").strip()
+with open('cb_key.txt', 'r', encoding='utf-8') as f:
+    CB_API_KEY = (f.read() or "").strip()
+with open('cb_secret.txt', 'r', encoding='utf-8') as f:
+    CB_API_SECRET = (f.read() or "").strip()
```

- Coinbase API key format: `organizations/{org_id}/apiKeys/{key_id}`
- Coinbase API secret: multi-line EC PEM private key (plain text, no base64 decoding)

### 2c. `__init__` Constructor

```diff
-self.api_key = API_KEY
-private_key_seed = base64.b64decode(BASE64_PRIVATE_KEY)
-self.private_key = SigningKey(private_key_seed)
-self.base_url = "https://trading.robinhood.com"
+self.client = RESTClient(api_key=CB_API_KEY, api_secret=CB_API_SECRET)
```

The SDK handles all HTTP requests and JWT authentication internally.

### 2d. Deleted Methods

These were Robinhood-specific HTTP/auth plumbing that the Coinbase SDK replaces entirely:

- **`make_api_request(method, path, body)`** — Manual HTTP request with signed headers
- **`get_authorization_header(method, path, body, timestamp)`** — ED25519 request signing
- **`_get_current_timestamp()`** — UTC timestamp for request signing

### 2e. Rewritten Data Methods

All methods were rewritten to use the Coinbase SDK while preserving the exact return shapes so the rest of the codebase (DCA logic, trailing profit, manage_trades loop) required zero changes.

**Critical implementation note**: The Coinbase SDK returns typed objects (e.g., `Account`, `ListAccountsResponse`) that are NOT `isinstance(dict)` but DO support `[]` bracket access. All methods use `[]` bracket access exclusively — never `isinstance` checks or `getattr`.

#### `get_account()`

| | Robinhood | Coinbase |
|---|-----------|---------|
| Call | `GET /api/v1/crypto/trading/accounts/` | `client.get_accounts()` |
| Parse | Direct JSON response | Find USD account in `resp["accounts"]`, read `acct["available_balance"]["value"]` |
| Return | `{"buying_power": ...}` | `{"buying_power": float}` (same shape) |

#### `get_holdings()`

| | Robinhood | Coinbase |
|---|-----------|---------|
| Call | `GET /api/v1/crypto/trading/holdings/` | `client.get_accounts()` |
| Parse | `response["results"]` list | Filter non-USD accounts with balance > 0 |
| Return | `{"results": [{"asset_code": str, "total_quantity": str}]}` | Same shape |

#### `get_trading_pairs()`

| | Robinhood | Coinbase |
|---|-----------|---------|
| Call | `GET /api/v1/crypto/trading/trading_pairs/` | `client.get_products(product_type="SPOT")` |
| Return | List of pairs | `list(resp["products"])` |

#### `get_orders(symbol)`

| | Robinhood | Coinbase |
|---|-----------|---------|
| Call | `GET /api/v1/crypto/trading/orders/?symbol=X` | `client.list_orders(product_ids=[X])` |
| Status normalization | Direct | `FILLED`→`filled`, `CANCELLED`/`CANCELED`→`canceled`, `EXPIRED`→`canceled`, `OPEN`→`pending` |
| Executions | Direct from response | Built from `filled_size` + `average_filled_price` |
| Return | `{"results": [{id, side, state, executions, ...}]}` | Same shape |

#### `get_price(symbols)`

| | Robinhood | Coinbase |
|---|-----------|---------|
| Call | N separate `GET /api/v1/crypto/marketdata/best_bid_ask/?symbol=X` | Single `client.get_best_bid_ask(product_ids=[...])` batch call |
| Ask price | `result["ask_inclusive_of_buy_spread"]` | `pricebook["asks"][0]["price"]` |
| Bid price | `result["bid_inclusive_of_sell_spread"]` | `pricebook["bids"][0]["price"]` |

The batch call is more efficient (1 API call vs N).

#### `_get_order_by_id(symbol, order_id)`

| | Robinhood | Coinbase |
|---|-----------|---------|
| Call | Fetch all orders via `get_orders()`, filter by ID | `client.get_order(order_id)` directly |

Direct lookup is faster and doesn't require fetching the full order list.

### 2f. `_wait_for_order_terminal()`

```diff
-terminal = {"filled", "canceled", "cancelled", "rejected", "failed", "error"}
+terminal = {"filled", "canceled", "cancelled", "rejected", "failed", "error", "expired"}
```

Added `"expired"` — Coinbase can expire unfilled orders.

### 2g. `place_buy_order()`

| | Robinhood | Coinbase |
|---|-----------|---------|
| Call | `POST /api/v1/crypto/trading/orders/` with `asset_quantity` (crypto amount) | `client.market_order_buy(product_id=symbol, quote_size=usd_amount)` |
| Sizing | Must calculate `usd / price` and handle precision retries (up to 5 attempts) | Coinbase accepts USD directly — no precision loop needed |
| Response | `response["id"]` | `resp["success_response"]["order_id"]` |

The Coinbase version is significantly simpler because `quote_size` accepts USD directly.

### 2h. `place_sell_order()`

| | Robinhood | Coinbase |
|---|-----------|---------|
| Call | `POST /api/v1/crypto/trading/orders/` | `client.market_order_sell(product_id=symbol, base_size=quantity)` |
| Fees | Complex extraction from multiple possible fee fields | `match["total_fees"]` single field |

Coinbase's fee reporting is cleaner — single `total_fees` field vs Robinhood's multiple possible locations.

### 2i. Pre-existing Holdings Filter (post-migration tweak)

```diff
 avg_cost_basis = cost_basis.get(symbol, 0)

-if avg_cost_basis > 0:
-    gain_loss_percentage_buy = ...
-    gain_loss_percentage_sell = ...
-else:
-    gain_loss_percentage_buy = 0
-    gain_loss_percentage_sell = 0
-    print(f"  Warning: Average Cost Basis is 0 for {symbol}, ...")
+# Skip pre-existing holdings that the bot did not buy (no cost basis on record)
+if avg_cost_basis <= 0:
+    continue
+
+gain_loss_percentage_buy = ...
+gain_loss_percentage_sell = ...
```

**Why**: Unlike Robinhood (where holdings = only what the bot bought), Coinbase accounts often have pre-existing crypto holdings. Without this filter, the bot would display them as "Current Trades" with $0 cost basis and could potentially trigger DCA or trailing sell logic on positions it didn't open.

### 2j. Unchanged

- `_extract_fill_from_order()` — works with normalized `executions` format
- `calculate_cost_basis()` — works with normalized `get_orders()` output
- `manage_trades()` — calls the same method interfaces
- All DCA logic (neural + hardcoded triggers, rolling 24h window, multiplier)
- Trailing profit margin system (5%/2.5% start, 0.5% trail gap)
- Trade recording, PnL ledger, account value history
- GUI status output formatting

---

## 3. pt_thinker.py — Real-Time AI Price Data

### 3a. Replaced Price Data Class

```diff
-from nacl.signing import SigningKey
+from coinbase.rest import RESTClient
```

**Removed**: `RobinhoodMarketData` class (~90 lines) — manual HTTP client with ED25519 signing, session management, timestamp generation, and authorization headers.

**Added**: `CoinbaseMarketData` class (~15 lines) — wraps `RESTClient.get_best_bid_ask()`.

```python
class CoinbaseMarketData:
    def __init__(self, api_key: str, api_secret: str):
        self.client = RESTClient(api_key=api_key, api_secret=api_secret)

    def get_current_ask(self, symbol: str) -> float:
        resp = self.client.get_best_bid_ask(product_ids=[symbol])
        pricebooks = resp["pricebooks"]
        return float(pricebooks[0]["asks"][0]["price"])
```

### 3b. Updated Singleton Wrapper

```diff
-def robinhood_current_ask(symbol: str) -> float:
+def coinbase_current_ask(symbol: str) -> float:
```

Reads `cb_key.txt` / `cb_secret.txt` instead of `r_key.txt` / `r_secret.txt`.

### 3c. Updated Call Site

```diff
-current = robinhood_current_ask(rh_symbol)
+current = coinbase_current_ask(cb_symbol)
```

### 3d. Removed Unused Imports

```diff
-import base64
-import hashlib
-import hmac
```

### 3e. Unchanged

- All KuCoin candle code (public API, no account needed)
- kNN pattern matching logic
- Signal file writing (long_dca_signal.txt, short_dca_signal.txt, etc.)
- Memory weight updates and learning
- All timeframe processing

---

## 4. pt_hub.py — GUI Credential Wizard

### 4a. File Paths

```diff
-key_path = os.path.join(self.project_dir, "r_key.txt")
-secret_path = os.path.join(self.project_dir, "r_secret.txt")
+key_path = os.path.join(self.project_dir, "cb_key.txt")
+secret_path = os.path.join(self.project_dir, "cb_secret.txt")
```

### 4b. Wizard Replacement

The Robinhood wizard was 3 steps (~250 lines):
1. **Generate Keys** — Create ED25519 keypair, show public key to copy
2. **Paste API Key** — User creates credential on Robinhood with the public key, gets back an API key
3. **Save** — Write `r_key.txt` (API key) + `r_secret.txt` (base64-encoded private key seed)

The Coinbase wizard is 2 steps (~85 lines):
1. **Paste API Key Name** — Single-line Entry field for `organizations/{org}/apiKeys/{key}`
2. **Paste API Secret** — Multi-line Text widget for EC PEM private key
3. **Save** — Write `cb_key.txt` + `cb_secret.txt`

**Why simpler**: Coinbase generates both the key and secret on their end. No local key generation needed.

### 4c. Test Credentials Button

```diff
-# Robinhood: manual HTTP request with ED25519 signing
-resp = requests.get(f"{base_url}{path}", headers=headers, timeout=10)
+# Coinbase: SDK handles auth
+client = RESTClient(api_key=api_key, api_secret=api_secret)
+resp = client.get_best_bid_ask(product_ids=["BTC-USD"])
```

### 4d. Label Updates

All user-facing text changed from "Robinhood" to "Coinbase":
- "Robinhood API:" → "Coinbase API:"
- "Open Robinhood API Credentials page" → "Open Coinbase API Portal"
- Error messages, wizard instructions, etc.

### 4e. Removed

- `_copy_to_clipboard()` helper (was only used for public key copy)
- ED25519 key generation logic
- Base64 encoding/decoding of keys
- `import base64`, `import platform`
- Robinhood-specific sanity checks (API key length, 64-byte seed normalization)

---

## 5. pt_trainer.py — Training Progress Logging

**Not related to migration** — added for usability since training can take several minutes with no visible output.

Added `_log()` function that prints timestamped `[TRAINER]` messages with `flush=True` so the Hub's Trainers tab shows output in real time.

Log points:
- Training start (coin + timeframes)
- Each timeframe start
- Candle download progress (count + percentage)
- Download complete + parse start
- Processing progress (every 500 candles)
- Timeframe finish
- All timeframes complete (with elapsed time)

---

## 6. Symbol Format

Both Robinhood and Coinbase use the same `{ASSET}-USD` format (e.g., `BTC-USD`, `SOL-USD`), so no symbol mapping was needed anywhere in the codebase.

---

## 7. Credential File Format

| | Robinhood | Coinbase |
|---|-----------|---------|
| Key file | `r_key.txt` — API key string (e.g., `rh-api-...`) | `cb_key.txt` — API key name (e.g., `organizations/{org}/apiKeys/{key}`) |
| Secret file | `r_secret.txt` — Base64-encoded ED25519 private key seed (32 bytes) | `cb_secret.txt` — EC PEM private key (multi-line, `-----BEGIN EC PRIVATE KEY-----`) |
| Auth method | ED25519 request signing (manual) | JWT (handled by SDK) |

---

## Summary

The migration removed ~800 lines of Robinhood-specific HTTP/auth plumbing and replaced it with ~565 lines using the Coinbase SDK. The SDK handles JWT authentication, request signing, and HTTP transport internally, making the code significantly simpler. All AI logic, trading strategy, DCA mechanics, and KuCoin candle data remain completely unchanged.
