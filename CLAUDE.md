# PowerTrader_AI — Claude Context

## Project Overview
Automated crypto trading bot (Coinbase Advanced Trade API) with kNN price prediction AI.
Fork of [garagesteve1/PowerTrader_AI](https://github.com/garagesteve1/PowerTrader_AI), migrated from Robinhood to Coinbase.
Repo: `BuberryWorldwide/PowerTrader_AI`

## Architecture

| File | Lines | Role |
|------|-------|------|
| `pt_hub.py` | ~5765 | tkinter GUI — launch/stop processes, charts, settings, manual controls |
| `pt_trader.py` | ~2360 | Trade execution — Coinbase orders, DCA, trailing profit margin |
| `pt_thinker.py` | ~1078 | AI signals — kNN pattern matching, writes signal files per coin |
| `pt_trainer.py` | ~unchanged | Training — downloads KuCoin candles, builds pattern memory |
| `pt_creds.py` | ~141 | Credential encryption — Fernet+PBKDF2, encrypt/decrypt/load helpers |

## Deployment
- **Runs on:** LXC 114 (`powertrader`) on Proxmox host `pve`
- **Path on LXC:** `/home/nhac/PowerTrader_AI/`
- **Access:** `ssh root@pve` then `pct exec 114 -- <command>`
- **Deploy workflow:** tarball locally → `scp` to PVE → `pct push 114` → `tar xzf` → `chown nhac:nhac`
- **Launch:** Start `pt_hub.py` from NoMachine GUI on LXC 114

## Key Data Files (runtime, in `hub_data/`)
- `trader_status.json` — current positions, account value, DCA state
- `trade_history.jsonl` — completed trades log
- `signal_log.jsonl` — AI decision audit trail (ENTRY/SKIP/DCA/HOLD/TRAIL_SELL)
- `pnl_ledger.json` — P&L tracking, pending orders
- `account_value_history.jsonl` — account value over time (grows unbounded, needs rotation)
- `runner_ready.json` — thinker readiness gate for trader startup
- `manual_command.json` — GUI→trader manual buy/sell commands (ephemeral)

## Known Issues & Gotchas

### Coinbase SDK hangs (CRITICAL)
- `coinbase-advanced-py` `RESTClient` has NO default timeout
- `get_order()` can hang indefinitely for certain order IDs (not 404, just blocks)
- **Fix applied:** `RESTClient(timeout=10)` on both trader and thinker clients
- Always use `timeout=` param when creating RESTClient instances

### pt_thinker.py CPU spin loops (FIXED)
- Multiple `while True` retry loops had zero sleep on exception paths
- Coinbase retry (line ~700): now `time.sleep(2)` on exception
- KuCoin parse failure (line ~538): now `time.sleep(0.5)` on bad float
- Main loop: increased from 0.15s to 2s between full sweeps
- Without these fixes, 2 coins x 7 timeframes x 6.6 iter/sec = 99% CPU

### pnl_ledger pending orders can get stuck
- If trader crashes between order placement and completion tracking, pending entry stays
- `_reconcile_pending_orders()` runs on startup to clean up, but if the order ID triggers
  the SDK hang bug, reconciliation itself hangs
- Manual fix: clear `pending_orders` in `pnl_ledger.json` before restart

### account_value_history.jsonl grows unbounded
- Currently ~16K lines / 1.1MB and growing
- No rotation implemented yet — will need cleanup or rotation logic

## Credentials
- Plaintext: `cb_key.txt` + `cb_secret.txt` (on LXC 114)
- Encrypted: `cb_credentials.enc` + `cb_credentials.salt` (not yet enabled on LXC)
- Passphrase via `POWERTRADER_PASSPHRASE` env var or GUI prompt
- All credential files are in `.gitignore`

## Feature Branch History
- `feature/observability-and-controls` — 8 improvements (now merged to main):
  1. Timestamped logging (`_log()` helper)
  2. Critical exception logging (11 blocks)
  3. Bot-only holdings filter (`get_bot_holdings()`)
  4. Signal decision log (JSONL)
  5. Manual buy/sell controls (GUI + trader polling)
  6. P&L chart (cumulative step chart)
  7. Encrypted credentials at rest
  8. CPU spin loop + SDK timeout fixes

## Quick Commands
```bash
# Deploy to LXC 114
tar czf /tmp/pt_deploy.tar.gz pt_trader.py pt_thinker.py pt_hub.py pt_creds.py
scp /tmp/pt_deploy.tar.gz root@pve:/tmp/
ssh root@pve "pct push 114 /tmp/pt_deploy.tar.gz /tmp/pt_deploy.tar.gz && pct exec 114 -- tar xzf /tmp/pt_deploy.tar.gz -C /home/nhac/PowerTrader_AI/ && pct exec 114 -- chown -R nhac:nhac /home/nhac/PowerTrader_AI/"

# Kill runaway processes
ssh root@pve "pct exec 114 -- pkill -f 'python.*pt_'"

# Check CPU
ssh root@pve "pct exec 114 -- ps aux --sort=-%cpu | head -5"

# Clear stuck pending orders
ssh root@pve "pct exec 114 -- python3 -c \"import json; p='/home/nhac/PowerTrader_AI/hub_data/pnl_ledger.json'; d=json.load(open(p)); d['pending_orders']={}; json.dump(d,open(p,'w'),indent=2); print('cleared')\""
```
