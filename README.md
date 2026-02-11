# PowerTrader_AI (Coinbase Fork)

Fully automated crypto trading powered by a custom price prediction AI and a structured/tiered DCA system.

This is a fork of [PowerTrader_AI](https://github.com/garagesteve1/PowerTrader_AI) migrated from Robinhood to **Coinbase Advanced Trade API** using the official `coinbase-advanced-py` SDK.

---

## What Changed from Upstream

| Component | Before (Upstream) | After (This Fork) |
|-----------|-------------------|-------------------|
| Broker | Robinhood Crypto Trading API | Coinbase Advanced Trade API |
| Auth | ED25519 signing via `PyNaCl` | JWT via `coinbase-advanced-py` SDK |
| Credentials | `r_key.txt` + `r_secret.txt` (base64 key) | `cb_key.txt` + `cb_secret.txt` (API key + PEM secret) |
| Price data (live) | Robinhood `best_bid_ask` endpoint | Coinbase `get_best_bid_ask()` SDK method |
| Price data (candles) | KuCoin public API (no account needed) | **Unchanged** — still KuCoin public API |
| AI / kNN logic | `pt_trainer.py` + `pt_thinker.py` | **Unchanged** |
| DCA strategy | `pt_trader.py` manage_trades loop | **Unchanged** (same logic, different broker calls) |
| GUI | `pt_hub.py` with Robinhood wizard | `pt_hub.py` with Coinbase wizard |

**Files modified:** `requirements.txt`, `pt_trader.py`, `pt_thinker.py`, `pt_hub.py`
**Files NOT modified:** `pt_trainer.py` (KuCoin candles only, no broker dependency)

---

## How It Works

PowerTrader AI has four components:

| File | Role |
|------|------|
| `pt_hub.py` | GUI dashboard — launch/stop everything, view charts, change settings |
| `pt_trainer.py` | Downloads candle history from KuCoin and trains the kNN pattern memory |
| `pt_thinker.py` | Runs the AI in real-time — compares live prices against predicted levels, writes signal files |
| `pt_trader.py` | Reads signals, manages positions, places buy/sell orders on Coinbase |

### The AI

It's a kNN (k-Nearest Neighbors) pattern matcher. For each coin, across timeframes from 1 hour to 1 week:

1. **Training**: Scans the entire candle history, saving each pattern and what happened next
2. **Prediction**: Takes a weighted average of the closest historical patterns to the current one, producing a predicted candle (high + low) per timeframe
3. **Learning**: After each candle closes, adjusts pattern weights based on accuracy

The blue lines (predicted lows) and orange lines (predicted highs) on the Hub's charts are these predictions.

### Trading Strategy

- **Entry**: When the current ask price drops below 3+ predicted low levels (LONG signal >= 3, SHORT signal = 0) — the trade start level is configurable in settings
- **DCA (Dollar Cost Averaging)**: If price keeps dropping, buys more at deeper levels. Uses whichever triggers first: the next AI level crossing, or a hardcoded drawdown percentage. Max 2 DCA buys per rolling 24-hour window
- **Exit**: Trailing profit margin. Starts at 5% gain (2.5% if any DCA happened). Once price exceeds the margin, it trails 0.5% behind the peak. Sells when price drops below the trailing line

### No Stop Loss (by design)

The original author's philosophy: spot trading has no liquidation risk, so rather than sell at a loss, hold and DCA deeper. This is a long-only, conviction-based strategy.

---

## Setup

### Prerequisites

- Python 3.10+
- A Coinbase account with funds
- Coinbase Advanced Trade API keys

### Step 1 — Install Dependencies

```bash
cd /path/to/PowerTrader_AI
pip install -r requirements.txt
```

This installs: `coinbase-advanced-py`, `requests`, `psutil`, `matplotlib`, `colorama`, `cryptography`, `kucoin-python`

### Step 2 — Get Coinbase API Credentials

1. Go to https://portal.cdp.coinbase.com/access/api
2. Click **Create API Key**
3. Give it a nickname (e.g., `PowerTraderAI`)
4. Under **API restrictions**, enable **Trade** permission
5. **Important**: Expand **Advanced Settings** and select **ECDSA** (not Ed25519) — the SDK requires ECDSA
6. Complete 2FA verification
7. Copy the **API Key Name** — looks like: `organizations/{org_id}/apiKeys/{key_id}`
8. Copy or download the **API Secret** — a multi-line PEM key starting with `-----BEGIN EC PRIVATE KEY-----`

### Step 3 — Save Credentials

You can either use the GUI wizard (Step 4) or create the files manually:

```bash
# In the PowerTrader_AI directory:
echo -n 'organizations/YOUR_ORG/apiKeys/YOUR_KEY' > cb_key.txt
# For the secret, paste the full PEM including headers:
cat > cb_secret.txt << 'EOF'
-----BEGIN EC PRIVATE KEY-----
YOUR_KEY_CONTENT_HERE
-----END EC PRIVATE KEY-----
EOF
```

Keep these files private. They are your trading credentials.

### Step 4 — Launch the Hub

```bash
python pt_hub.py
```

### Step 5 — Configure Settings

In the Hub, open **Settings**:

1. **Main Neural Folder** — set to the folder containing `pt_hub.py`
2. **Coins** — start with **BTC** (add more later)
3. **Coinbase API** — if you created the files manually, it should show "Configured". Otherwise, click **Setup Wizard** to paste your credentials
4. Click **Save**

### Step 6 — Train

1. Click **Train All** in the Hub
2. Wait for training to finish (downloads KuCoin candle history and builds pattern memory)
3. Each coin gets its own folder — BTC uses the main folder, others get subfolders (e.g., `ETH/`)

### Step 7 — Start Trading

1. Click **Start All**
2. The Hub starts `pt_thinker.py` first (AI signals), waits for it to be ready, then starts `pt_trader.py` (executes trades)

That's it. The Hub shows real-time charts with predicted levels and manages both processes.

---

## Settings Reference

| Setting | Default | Description |
|---------|---------|-------------|
| Trade Start Level | 3 | How many predicted low levels price must cross to trigger a buy |
| Start Allocation % | 0.5% | Percentage of account value for the initial buy |
| DCA Multiplier | 2.0x | Each DCA buy is this multiple of the previous buy size |
| DCA Levels | -2.5%, -5%, -10%, -20%, -30%, -40%, -50% | Hardcoded drawdown triggers for each DCA stage |
| Max DCA Buys / 24h | 2 | Rate limit on DCA buys per coin per rolling 24-hour window |
| Profit Margin (no DCA) | 5.0% | Gain required to start trailing (when no DCA buys happened) |
| Profit Margin (with DCA) | 2.5% | Gain required to start trailing (when DCA buys happened) |
| Trailing Gap | 0.5% | How far behind the peak the trailing sell line sits |

All settings are editable in the Hub's Settings panel and saved to `gui_settings.json`.

---

## Neural Levels (LONG/SHORT)

The Hub displays signal strength levels for each coin:

- **LONG levels** (1-7): How many predicted LOW prices the current ask is below. Higher = stronger buy signal
- **SHORT levels** (1-7): How many predicted HIGH prices the current ask is above. Higher = stronger no-start signal

A trade starts when **LONG >= Trade Start Level** (default 3) and **SHORT = 0**.

---

## File Structure

```
PowerTrader_AI/
  pt_hub.py           # GUI dashboard
  pt_trainer.py       # AI training (KuCoin candle data)
  pt_thinker.py       # AI real-time signals
  pt_trader.py        # Trade execution (Coinbase)
  requirements.txt    # Python dependencies
  cb_key.txt          # Coinbase API key (you create this)
  cb_secret.txt       # Coinbase API secret PEM (you create this)
  gui_settings.json   # Settings (created by Hub)
  hub_data/           # Trade history, PnL ledger, status (created at runtime)
  ETH/                # Per-coin subfolder (created by trainer)
  XRP/                # etc.
```

---

## Adding More Coins

1. Open **Settings** in the Hub
2. Add the coin ticker (e.g., `ETH`, `SOL`)
3. Click **Save**
4. Click **Train All** and wait for training to complete
5. Click **Start All**

The coin must be available on both KuCoin (for candle history) and Coinbase (for trading) as a `-USD` pair.

---

## Troubleshooting

**"Coinbase API credentials not found"** — Create `cb_key.txt` and `cb_secret.txt` in the PowerTrader_AI folder, or use the Setup Wizard in Settings.

**Training takes a long time** — Normal for first run. It downloads full candle history across all timeframes. Subsequent trains are faster.

**No trades happening** — The bot only buys when the AI signal reaches the Trade Start Level (default 3). This can take time. Check the Neural Levels display in the Hub to see current signal strength.

**Price fetch errors** — Verify your Coinbase API key has the correct permissions and uses ECDSA signature algorithm.

---

## License

PowerTrader AI is released under the **Apache 2.0** license.

---

IMPORTANT: This software places real trades automatically. You are responsible for everything it does to your money and your account. Keep your API keys private. This is not financial advice. You are fully responsible for all gains, losses, and security of your credentials.
