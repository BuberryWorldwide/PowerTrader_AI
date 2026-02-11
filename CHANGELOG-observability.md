# Observability & Controls Update

Branch: `feature/observability-and-controls`
Date: 2026-02-11
8 improvements to logging, filtering, GUI observability, manual controls, and credential security.

---

## Files Changed

| File | Change |
|------|--------|
| `pt_trader.py` | Timestamped logging, error logging, bot-only holdings filter, signal log, manual command polling |
| `pt_hub.py` | Signal Log panel, Manual Buy/Sell buttons, P&L chart tab, encrypted credential support |
| `pt_thinker.py` | Credential loading via `pt_creds.py` |
| `pt_creds.py` | **New** — Fernet+PBKDF2 encryption module for API credentials |
| `.gitignore` | Added `cb_credentials.enc` and `cb_credentials.salt` |

---

## Feature Details

### 1. Timestamped Logging (`pt_trader.py`)
- Added `_log(msg)` module-level helper: `[HH:MM:SS] message`
- Replaced ~60 `print()` calls across `__init__`, `initialize_dca_levels()`, `_reconcile_pending_orders()`, `_wait_for_order_terminal()`, `manage_trades()`, and `run()`
- Hub already prepends `[TRADER]` via reader thread — no duplication

### 2. Critical Exception Logging (`pt_trader.py`)
- 11 silent `except Exception: pass` blocks now log `[ERROR]` with context:
  - API calls: `get_account`, `get_holdings`, `get_orders`, `get_price`, `get_trading_pairs`
  - Order placement: `place_buy_order`, `place_sell_order` (includes full `traceback.format_exc()`)
  - Trade recording: `_record_trade` P&L calc blocks (2 blocks)
  - Per-holding calc in `manage_trades()`, status write
- 57 other blocks intentionally remain silent (settings parsing, type conversions, caching fallbacks)

### 3. Bot-Only Holdings Filter (`pt_trader.py`)
- Added `get_bot_holdings()` method: wraps `get_holdings()`, filters to `crypto_symbols` only
- `initialize_dca_levels()` now uses `get_bot_holdings()` — stops calling `get_orders()` for pre-existing coins like TOSHI/HBAR/MANA/AUCTION/USDC
- `calculate_cost_basis()` uses `get_bot_holdings()` — eliminates `{'HBAR': 0.0, ...}` noise
- `get_holdings()` stays unfiltered in `manage_trades()` — total account value must include all assets
- Added early `_refresh_paths_and_symbols()` call in `__init__` so `crypto_symbols` is populated before these methods run

### 4. Signal Decision Log (`pt_trader.py` + `pt_hub.py`)
**Trader side:**
- `SIGNAL_LOG_PATH` → `hub_data/signal_log.jsonl`
- `_log_signal(symbol, action, reason, long_level, short_level, details)` → appends JSONL
- Actions logged: `ENTRY`, `SKIP`, `DCA`, `DCA_SKIP`, `TRAIL_SELL`, `HOLD`
- Logged at each decision point in `manage_trades()`:
  - New trade loop: ENTRY (on buy) or SKIP (signal too low)
  - DCA logic: DCA (on trigger), DCA_SKIP (24h limit or insufficient funds)
  - Trailing PM: TRAIL_SELL (price crossed below trailing line)
  - End of per-holding loop: HOLD (no DCA trigger)
- Auto-rotates to last 500 lines at top of `manage_trades()`

**GUI side:**
- New `tk.Listbox` panel in right-bottom split between Current Trades and Trade History
- Shows last 100 entries newest-first
- Format: `HH:MM:SS | BTC   | SKIP         | L:2 S:0 | Need L>=3 S=0`
- Color-coded: green (ENTRY/DCA), red (TRAIL_SELL), muted (SKIP/HOLD/DCA_SKIP)
- Mtime-cached refresh (fast skip when unchanged)

### 5. Manual Buy/Sell Controls (`pt_trader.py` + `pt_hub.py`)
**GUI side:**
- Controls bar below Current Trades table:
  - Coin dropdown (from `crypto_symbols`) + dollar amount entry + "Buy" button + "Sell All" button
- Confirmation dialog before each action
- Writes `manual_command.json` atomically via `_safe_write_json()` — trader picks it up next loop
- Coin dropdown updates when coins change in settings

**Trader side:**
- `_poll_manual_command()` called at top of `manage_trades()` each iteration
- Reads JSON command, executes buy/sell, deletes file
- Buy: `place_buy_order()` with `tag="MANUAL_BUY"`, recalculates cost basis + DCA levels
- Sell: finds holding qty, `place_sell_order()` with `tag="MANUAL_SELL"`, resets DCA window + trailing PM

### 6. P&L Chart (`pt_hub.py`)
- New `PnLChart` class (same pattern as `AccountValueChart`):
  - Reads `trade_history.jsonl`, filters to sells with `realized_profit_usd`
  - Plots cumulative P&L as step function
  - $0 breakeven horizontal dashed line
  - Green dots for winning trades, red for losses
  - Y-axis: `$+X.XX` / `$-X.XX` format
  - Title shows final cumulative P&L colored green/red
- New "P&L" tab button in chart tabs (alongside ACCOUNT + coin tabs)
- Clicking P&L tab forces immediate refresh
- Refreshes on same chart timer cycle (mtime-cached)
- Persists across `_rebuild_coin_chart_tabs()` (settings changes)

### 7. Encrypted Credentials at Rest (`pt_creds.py` + all files)
**New module `pt_creds.py`:**
- `encrypt_credentials(base_dir, passphrase, key, secret)` → writes `cb_credentials.enc` + `cb_credentials.salt`
- `decrypt_credentials(base_dir, passphrase)` → returns `(key, secret)`
- `load_credentials(base_dir)` → tries encrypted first (env var `POWERTRADER_PASSPHRASE` or `getpass`), falls back to plaintext
- `has_encrypted_credentials()` / `has_plaintext_credentials()` — detection helpers
- `delete_plaintext_credentials()` — removes `cb_key.txt` + `cb_secret.txt` after encryption
- Uses Fernet + PBKDF2 (480,000 iterations, SHA256) — `cryptography` already in `requirements.txt`

**Integration:**
- `pt_trader.py`: replaced plaintext file reads with `load_credentials()`
- `pt_thinker.py`: replaced plaintext file reads with `load_credentials()` (fallback to direct reads if `pt_creds` unavailable)
- Hub settings wizard: after saving plaintext, offers to encrypt + delete originals via passphrase dialog with confirmation
- Hub `start_trader()`: if encrypted creds exist, prompts for passphrase via GUI dialog, passes via `POWERTRADER_PASSPHRASE` env var to subprocess
- Hub API status display: shows "Configured (encrypted)" when `.enc` file detected
- `.gitignore`: added `cb_credentials.enc` and `cb_credentials.salt`

---

## Verification Checklist

1. Start Hub → Start All → check trader log shows `[HH:MM:SS]` timestamps on every line
2. Trigger an API error (e.g., invalid symbol) → verify `[ERROR]` appears in log instead of silent failure
3. Check init output → only BTC/SOL in cost basis and DCA levels, not TOSHI/HBAR/etc.
4. Watch Signal Log panel → see SKIP/ENTRY/HOLD decisions updating each cycle
5. Click Buy $1 BTC → confirm dialog → verify order appears in trade history
6. Click Sell All → confirm → verify sell recorded
7. Click P&L tab → verify chart shows cumulative P&L (or "no sells yet" if none)
8. Run encryption wizard → verify cb_key.txt/cb_secret.txt deleted, .enc/.salt created → restart trader → verify it prompts/decrypts and connects
