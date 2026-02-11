import datetime
import json
import uuid
import time
import math
from typing import Any, Dict, Optional
import os
import colorama
from colorama import Fore, Style
import traceback
from coinbase.rest import RESTClient

# -----------------------------
# GUI HUB OUTPUTS
# -----------------------------
HUB_DATA_DIR = os.environ.get("POWERTRADER_HUB_DIR", os.path.join(os.path.dirname(__file__), "hub_data"))
os.makedirs(HUB_DATA_DIR, exist_ok=True)

TRADER_STATUS_PATH = os.path.join(HUB_DATA_DIR, "trader_status.json")
TRADE_HISTORY_PATH = os.path.join(HUB_DATA_DIR, "trade_history.jsonl")
PNL_LEDGER_PATH = os.path.join(HUB_DATA_DIR, "pnl_ledger.json")
ACCOUNT_VALUE_HISTORY_PATH = os.path.join(HUB_DATA_DIR, "account_value_history.jsonl")
SIGNAL_LOG_PATH = os.path.join(HUB_DATA_DIR, "signal_log.jsonl")
MANUAL_COMMAND_PATH = os.path.join(HUB_DATA_DIR, "manual_command.json")



# Initialize colorama
colorama.init(autoreset=True)


def _log(msg: str) -> None:
	"""Timestamped print for trader log lines."""
	print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

# -----------------------------
# GUI SETTINGS (coins list + main_neural_dir)
# -----------------------------
_GUI_SETTINGS_PATH = os.environ.get("POWERTRADER_GUI_SETTINGS") or os.path.join(
	os.path.dirname(os.path.abspath(__file__)),
	"gui_settings.json"
)

_gui_settings_cache = {
	"mtime": None,
	"coins": ['BTC', 'ETH', 'XRP', 'BNB', 'DOGE'],  # fallback defaults
	"main_neural_dir": None,
	"trade_start_level": 3,
	"start_allocation_pct": 0.005,
	"dca_multiplier": 2.0,
	"dca_levels": [-2.5, -5.0, -10.0, -20.0, -30.0, -40.0, -50.0],
	"max_dca_buys_per_24h": 2,
	"dca_cooldown_minutes": 60,

	# Trailing PM settings (defaults match previous hardcoded behavior)
	"pm_start_pct_no_dca": 5.0,
	"pm_start_pct_with_dca": 2.5,
	"trailing_gap_pct": 0.5,
}







def _load_gui_settings() -> dict:
	"""
	Reads gui_settings.json and returns a dict with:
	- coins: uppercased list
	- main_neural_dir: string (may be None)
	Caches by mtime so it is cheap to call frequently.
	"""
	try:
		if not os.path.isfile(_GUI_SETTINGS_PATH):
			return dict(_gui_settings_cache)

		mtime = os.path.getmtime(_GUI_SETTINGS_PATH)
		if _gui_settings_cache["mtime"] == mtime:
			return dict(_gui_settings_cache)

		with open(_GUI_SETTINGS_PATH, "r", encoding="utf-8") as f:
			data = json.load(f) or {}

		coins = data.get("coins", None)
		if not isinstance(coins, list) or not coins:
			coins = list(_gui_settings_cache["coins"])
		coins = [str(c).strip().upper() for c in coins if str(c).strip()]
		if not coins:
			coins = list(_gui_settings_cache["coins"])

		main_neural_dir = data.get("main_neural_dir", None)
		if isinstance(main_neural_dir, str):
			main_neural_dir = main_neural_dir.strip() or None
		else:
			main_neural_dir = None

		trade_start_level = data.get("trade_start_level", _gui_settings_cache.get("trade_start_level", 3))
		try:
			trade_start_level = int(float(trade_start_level))
		except Exception:
			trade_start_level = int(_gui_settings_cache.get("trade_start_level", 3))
		trade_start_level = max(1, min(trade_start_level, 7))

		start_allocation_pct = data.get("start_allocation_pct", _gui_settings_cache.get("start_allocation_pct", 0.005))
		try:
			start_allocation_pct = float(str(start_allocation_pct).replace("%", "").strip())
		except Exception:
			start_allocation_pct = float(_gui_settings_cache.get("start_allocation_pct", 0.005))
		if start_allocation_pct < 0.0:
			start_allocation_pct = 0.0

		dca_multiplier = data.get("dca_multiplier", _gui_settings_cache.get("dca_multiplier", 2.0))
		try:
			dca_multiplier = float(str(dca_multiplier).strip())
		except Exception:
			dca_multiplier = float(_gui_settings_cache.get("dca_multiplier", 2.0))
		if dca_multiplier < 0.0:
			dca_multiplier = 0.0

		dca_levels = data.get("dca_levels", _gui_settings_cache.get("dca_levels", [-2.5, -5.0, -10.0, -20.0, -30.0, -40.0, -50.0]))
		if not isinstance(dca_levels, list) or not dca_levels:
			dca_levels = list(_gui_settings_cache.get("dca_levels", [-2.5, -5.0, -10.0, -20.0, -30.0, -40.0, -50.0]))
		parsed = []
		for v in dca_levels:
			try:
				parsed.append(float(v))
			except Exception:
				pass
		if parsed:
			dca_levels = parsed
		else:
			dca_levels = list(_gui_settings_cache.get("dca_levels", [-2.5, -5.0, -10.0, -20.0, -30.0, -40.0, -50.0]))

		max_dca_buys_per_24h = data.get("max_dca_buys_per_24h", _gui_settings_cache.get("max_dca_buys_per_24h", 2))
		try:
			max_dca_buys_per_24h = int(float(max_dca_buys_per_24h))
		except Exception:
			max_dca_buys_per_24h = int(_gui_settings_cache.get("max_dca_buys_per_24h", 2))
		if max_dca_buys_per_24h < 0:
			max_dca_buys_per_24h = 0

		dca_cooldown_minutes = data.get("dca_cooldown_minutes", _gui_settings_cache.get("dca_cooldown_minutes", 60))
		try:
			dca_cooldown_minutes = int(float(dca_cooldown_minutes))
		except Exception:
			dca_cooldown_minutes = int(_gui_settings_cache.get("dca_cooldown_minutes", 60))
		if dca_cooldown_minutes < 0:
			dca_cooldown_minutes = 0

		# --- Trailing PM settings ---
		pm_start_pct_no_dca = data.get("pm_start_pct_no_dca", _gui_settings_cache.get("pm_start_pct_no_dca", 5.0))
		try:
			pm_start_pct_no_dca = float(str(pm_start_pct_no_dca).replace("%", "").strip())
		except Exception:
			pm_start_pct_no_dca = float(_gui_settings_cache.get("pm_start_pct_no_dca", 5.0))
		if pm_start_pct_no_dca < 0.0:
			pm_start_pct_no_dca = 0.0

		pm_start_pct_with_dca = data.get("pm_start_pct_with_dca", _gui_settings_cache.get("pm_start_pct_with_dca", 2.5))
		try:
			pm_start_pct_with_dca = float(str(pm_start_pct_with_dca).replace("%", "").strip())
		except Exception:
			pm_start_pct_with_dca = float(_gui_settings_cache.get("pm_start_pct_with_dca", 2.5))
		if pm_start_pct_with_dca < 0.0:
			pm_start_pct_with_dca = 0.0

		trailing_gap_pct = data.get("trailing_gap_pct", _gui_settings_cache.get("trailing_gap_pct", 0.5))
		try:
			trailing_gap_pct = float(str(trailing_gap_pct).replace("%", "").strip())
		except Exception:
			trailing_gap_pct = float(_gui_settings_cache.get("trailing_gap_pct", 0.5))
		if trailing_gap_pct < 0.0:
			trailing_gap_pct = 0.0


		_gui_settings_cache["mtime"] = mtime
		_gui_settings_cache["coins"] = coins
		_gui_settings_cache["main_neural_dir"] = main_neural_dir
		_gui_settings_cache["trade_start_level"] = trade_start_level
		_gui_settings_cache["start_allocation_pct"] = start_allocation_pct
		_gui_settings_cache["dca_multiplier"] = dca_multiplier
		_gui_settings_cache["dca_levels"] = dca_levels
		_gui_settings_cache["max_dca_buys_per_24h"] = max_dca_buys_per_24h
		_gui_settings_cache["dca_cooldown_minutes"] = dca_cooldown_minutes

		_gui_settings_cache["pm_start_pct_no_dca"] = pm_start_pct_no_dca
		_gui_settings_cache["pm_start_pct_with_dca"] = pm_start_pct_with_dca
		_gui_settings_cache["trailing_gap_pct"] = trailing_gap_pct


		return {
			"mtime": mtime,
			"coins": list(coins),
			"main_neural_dir": main_neural_dir,
			"trade_start_level": trade_start_level,
			"start_allocation_pct": start_allocation_pct,
			"dca_multiplier": dca_multiplier,
			"dca_levels": list(dca_levels),
			"max_dca_buys_per_24h": max_dca_buys_per_24h,
			"dca_cooldown_minutes": dca_cooldown_minutes,

			"pm_start_pct_no_dca": pm_start_pct_no_dca,
			"pm_start_pct_with_dca": pm_start_pct_with_dca,
			"trailing_gap_pct": trailing_gap_pct,
		}




	except Exception:
		return dict(_gui_settings_cache)


def _build_base_paths(main_dir_in: str, coins_in: list) -> dict:
	"""
	Safety rule:
	- BTC uses main_dir directly
	- other coins use <main_dir>/<SYM> ONLY if that folder exists
	  (no fallback to BTC folder — avoids corrupting BTC data)
	"""
	out = {"BTC": main_dir_in}
	try:
		for sym in coins_in:
			sym = str(sym).strip().upper()
			if not sym:
				continue
			if sym == "BTC":
				out["BTC"] = main_dir_in
				continue
			sub = os.path.join(main_dir_in, sym)
			if os.path.isdir(sub):
				out[sym] = sub
	except Exception:
		pass
	return out


# Live globals (will be refreshed inside manage_trades())
crypto_symbols = ['BTC', 'ETH', 'XRP', 'BNB', 'DOGE']

# Default main_dir behavior if settings are missing
main_dir = os.getcwd()
base_paths = {"BTC": main_dir}
TRADE_START_LEVEL = 3
START_ALLOC_PCT = 0.005
DCA_MULTIPLIER = 2.0
DCA_LEVELS = [-2.5, -5.0, -10.0, -20.0, -30.0, -40.0, -50.0]
MAX_DCA_BUYS_PER_24H = 2
DCA_COOLDOWN_MINUTES = 60  # minimum minutes between DCA buys for the same coin

# Trailing PM hot-reload globals (defaults match previous hardcoded behavior)
TRAILING_GAP_PCT = 0.5
PM_START_PCT_NO_DCA = 5.0
PM_START_PCT_WITH_DCA = 2.5



_last_settings_mtime = None




def _refresh_paths_and_symbols():
	"""
	Hot-reload GUI settings while trader is running.
	Updates globals: crypto_symbols, main_dir, base_paths,
	                TRADE_START_LEVEL, START_ALLOC_PCT, DCA_MULTIPLIER, DCA_LEVELS, MAX_DCA_BUYS_PER_24H, DCA_COOLDOWN_MINUTES,
	                TRAILING_GAP_PCT, PM_START_PCT_NO_DCA, PM_START_PCT_WITH_DCA
	"""
	global crypto_symbols, main_dir, base_paths
	global TRADE_START_LEVEL, START_ALLOC_PCT, DCA_MULTIPLIER, DCA_LEVELS, MAX_DCA_BUYS_PER_24H, DCA_COOLDOWN_MINUTES
	global TRAILING_GAP_PCT, PM_START_PCT_NO_DCA, PM_START_PCT_WITH_DCA
	global _last_settings_mtime


	s = _load_gui_settings()
	mtime = s.get("mtime", None)

	# If settings file doesn't exist, keep current defaults
	if mtime is None:
		return

	if _last_settings_mtime == mtime:
		return

	_last_settings_mtime = mtime

	coins = s.get("coins") or list(crypto_symbols)
	mndir = s.get("main_neural_dir") or main_dir
	TRADE_START_LEVEL = max(1, min(int(s.get("trade_start_level", TRADE_START_LEVEL) or TRADE_START_LEVEL), 7))
	START_ALLOC_PCT = float(s.get("start_allocation_pct", START_ALLOC_PCT) or START_ALLOC_PCT)
	if START_ALLOC_PCT < 0.0:
		START_ALLOC_PCT = 0.0

	DCA_MULTIPLIER = float(s.get("dca_multiplier", DCA_MULTIPLIER) or DCA_MULTIPLIER)
	if DCA_MULTIPLIER < 0.0:
		DCA_MULTIPLIER = 0.0

	DCA_LEVELS = list(s.get("dca_levels", DCA_LEVELS) or DCA_LEVELS)

	try:
		MAX_DCA_BUYS_PER_24H = int(float(s.get("max_dca_buys_per_24h", MAX_DCA_BUYS_PER_24H) or MAX_DCA_BUYS_PER_24H))
	except Exception:
		MAX_DCA_BUYS_PER_24H = int(MAX_DCA_BUYS_PER_24H)
	if MAX_DCA_BUYS_PER_24H < 0:
		MAX_DCA_BUYS_PER_24H = 0

	try:
		DCA_COOLDOWN_MINUTES = int(float(s.get("dca_cooldown_minutes", DCA_COOLDOWN_MINUTES) or DCA_COOLDOWN_MINUTES))
	except Exception:
		DCA_COOLDOWN_MINUTES = int(DCA_COOLDOWN_MINUTES)
	if DCA_COOLDOWN_MINUTES < 0:
		DCA_COOLDOWN_MINUTES = 0

	# Trailing PM hot-reload values
	TRAILING_GAP_PCT = float(s.get("trailing_gap_pct", TRAILING_GAP_PCT) or TRAILING_GAP_PCT)
	if TRAILING_GAP_PCT < 0.0:
		TRAILING_GAP_PCT = 0.0

	PM_START_PCT_NO_DCA = float(s.get("pm_start_pct_no_dca", PM_START_PCT_NO_DCA) or PM_START_PCT_NO_DCA)
	if PM_START_PCT_NO_DCA < 0.0:
		PM_START_PCT_NO_DCA = 0.0

	PM_START_PCT_WITH_DCA = float(s.get("pm_start_pct_with_dca", PM_START_PCT_WITH_DCA) or PM_START_PCT_WITH_DCA)
	if PM_START_PCT_WITH_DCA < 0.0:
		PM_START_PCT_WITH_DCA = 0.0


	# Keep it safe if folder isn't real on this machine
	if not os.path.isdir(mndir):
		mndir = os.getcwd()

	crypto_symbols = list(coins)
	main_dir = mndir
	base_paths = _build_base_paths(main_dir, crypto_symbols)






#API STUFF
CB_API_KEY = ""
CB_API_SECRET = ""

try:
    from pt_creds import load_credentials
    _base_dir = os.path.dirname(os.path.abspath(__file__))
    CB_API_KEY, CB_API_SECRET = load_credentials(_base_dir)
except Exception as e:
    CB_API_KEY = ""
    CB_API_SECRET = ""
    _log(f"[PowerTrader] Credential loading failed: {e}")

if not CB_API_KEY or not CB_API_SECRET:
    _log(
        "[PowerTrader] Coinbase API credentials not found. "
        "Open the GUI and go to Settings -> Coinbase API -> Setup / Update. "
        "That wizard will save cb_key.txt + cb_secret.txt so this trader can authenticate."
    )
    raise SystemExit(1)

class CryptoAPITrading:
    def __init__(self):
        _log("=" * 60)
        _log("  POWERTRADER AI — INITIALIZING")
        _log("=" * 60)

        # Load settings early so crypto_symbols is populated before cost basis / DCA init
        _refresh_paths_and_symbols()

        # keep a copy of the folder map (same idea as trader.py)
        self.path_map = dict(base_paths)

        _log("[INIT] Connecting to Coinbase API...")
        self.client = RESTClient(api_key=CB_API_KEY, api_secret=CB_API_SECRET, timeout=10)
        _log("[INIT] Coinbase client ready.")

        self.dca_levels_triggered = {}  # Track DCA levels for each crypto
        self.dca_levels = list(DCA_LEVELS)  # Hard DCA triggers (percent PnL)


        # --- Trailing profit margin (per-coin state) ---
        # Each coin keeps its own trailing PM line, peak, and "was above line" flag.
        self.trailing_pm = {}  # { "BTC": {"active": bool, "line": float, "peak": float, "was_above": bool}, . }
        self.trailing_gap_pct = float(TRAILING_GAP_PCT)  # % trail gap behind peak
        self.pm_start_pct_no_dca = float(PM_START_PCT_NO_DCA)
        self.pm_start_pct_with_dca = float(PM_START_PCT_WITH_DCA)

        # Track trailing-related settings so we can reset trailing state if they change
        self._last_trailing_settings_sig = (
            float(self.trailing_gap_pct),
            float(self.pm_start_pct_no_dca),
            float(self.pm_start_pct_with_dca),
        )


        _log("[INIT] Calculating cost basis...")
        self.cost_basis = self.calculate_cost_basis()  # Initialize cost basis at startup
        _log(f"[INIT] Cost basis: {self.cost_basis}")

        _log("[INIT] Initializing DCA levels from order history...")
        self.initialize_dca_levels()  # Initialize DCA levels based on historical buy orders
        _log(f"[INIT] DCA levels: {self.dca_levels_triggered}")

        # GUI hub persistence
        _log("[INIT] Loading PnL ledger...")
        self._pnl_ledger = self._load_pnl_ledger()
        _log("[INIT] Reconciling pending orders...")
        self._reconcile_pending_orders()


        # Cache last known bid/ask per symbol so transient API misses don't zero out account value
        self._last_good_bid_ask = {}

        # Cache last *complete* account snapshot so transient holdings/price misses can't write a bogus low value
        self._last_good_account_snapshot = {
            "total_account_value": None,
            "buying_power": None,
            "holdings_sell_value": None,
            "holdings_buy_value": None,
            "percent_in_trade": None,
        }

        # --- DCA rate-limit (per trade, per coin, rolling 24h window) ---
        self.max_dca_buys_per_24h = int(MAX_DCA_BUYS_PER_24H)
        self.dca_cooldown_minutes = int(DCA_COOLDOWN_MINUTES)
        self.dca_window_seconds = 24 * 60 * 60

        self._dca_buy_ts = {}         # { "BTC": [ts, ts, ...] } (DCA buys only)
        self._dca_last_sell_ts = {}   # { "BTC": ts_of_last_sell }
        self._seed_dca_window_from_history()

        _log("[INIT] Seeded DCA window from history.")
        _log("=" * 60)
        _log("  INITIALIZATION COMPLETE — STARTING TRADE LOOP")
        _log("=" * 60)








    def _atomic_write_json(self, path: str, data: dict) -> None:
        try:
            tmp = f"{path}.tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp, path)
        except Exception:
            pass

    def _append_jsonl(self, path: str, obj: dict) -> None:
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(obj) + "\n")
        except Exception:
            pass

    def _log_signal(self, symbol: str, action: str, reason: str,
                    long_level: int = 0, short_level: int = 0, details: dict = None) -> None:
        """Append a signal decision to the signal log (JSONL)."""
        try:
            entry = {
                "ts": time.time(),
                "time": datetime.datetime.now().strftime("%H:%M:%S"),
                "symbol": str(symbol).upper(),
                "action": action,
                "reason": reason,
                "long_level": int(long_level),
                "short_level": int(short_level),
            }
            if details:
                entry["details"] = details
            self._append_jsonl(SIGNAL_LOG_PATH, entry)
        except Exception:
            pass

    def _rotate_signal_log(self, max_lines: int = 500) -> None:
        """Truncate signal log to last max_lines entries."""
        try:
            if not os.path.isfile(SIGNAL_LOG_PATH):
                return
            with open(SIGNAL_LOG_PATH, "r", encoding="utf-8") as f:
                lines = f.readlines()
            if len(lines) > max_lines:
                with open(SIGNAL_LOG_PATH, "w", encoding="utf-8") as f:
                    f.writelines(lines[-max_lines:])
        except Exception:
            pass

    def _poll_manual_command(self) -> None:
        """Check for a manual buy/sell command from the GUI and execute it."""
        try:
            if not os.path.isfile(MANUAL_COMMAND_PATH):
                return
            with open(MANUAL_COMMAND_PATH, "r", encoding="utf-8") as f:
                cmd = json.load(f)
            # Delete file immediately to prevent re-execution
            os.remove(MANUAL_COMMAND_PATH)

            if not isinstance(cmd, dict):
                return

            action = str(cmd.get("action", "")).lower().strip()
            symbol = str(cmd.get("symbol", "")).upper().strip()
            if not symbol:
                return
            full_symbol = f"{symbol}-USD"

            if action == "buy":
                amount = float(cmd.get("amount_usd", 0))
                if amount < 1.0:
                    _log(f"[MANUAL] Buy amount too small: ${amount:.2f}")
                    return
                _log(f"[MANUAL] Executing BUY ${amount:.2f} of {full_symbol}")
                response = self.place_buy_order(
                    str(uuid.uuid4()), "buy", "market", full_symbol, amount, tag="MANUAL_BUY",
                )
                if response and isinstance(response, dict) and "errors" not in response:
                    _log(f"[MANUAL] Buy order placed successfully for {full_symbol}")
                    # Recalculate cost basis after manual buy
                    new_cb = self.calculate_cost_basis()
                    if new_cb:
                        self.cost_basis = new_cb
                    self.initialize_dca_levels()
                else:
                    _log(f"[MANUAL] Buy order FAILED for {full_symbol}")

            elif action == "sell":
                # Find holding qty for this symbol
                holdings = self.get_holdings()
                sell_qty = 0.0
                if holdings and "results" in holdings:
                    for h in holdings["results"]:
                        if str(h.get("asset_code", "")).upper() == symbol:
                            sell_qty = float(h.get("total_quantity", 0))
                            break
                if sell_qty <= 0:
                    _log(f"[MANUAL] No holdings found for {symbol}")
                    return
                _log(f"[MANUAL] Executing SELL ALL {sell_qty} of {full_symbol}")
                avg_cb = self.cost_basis.get(symbol, 0.0)
                response = self.place_sell_order(
                    str(uuid.uuid4()), "sell", "market", full_symbol, sell_qty,
                    avg_cost_basis=avg_cb if avg_cb > 0 else None, tag="MANUAL_SELL",
                )
                if response and isinstance(response, dict) and "errors" not in response:
                    _log(f"[MANUAL] Sell order placed successfully for {full_symbol}")
                    self._reset_dca_window_for_trade(symbol, sold=True)
                    self.trailing_pm.pop(symbol, None)
                    new_cb = self.calculate_cost_basis()
                    if new_cb:
                        self.cost_basis = new_cb
                    self.initialize_dca_levels()
                else:
                    _log(f"[MANUAL] Sell order FAILED for {full_symbol}")
            else:
                _log(f"[MANUAL] Unknown action: {action}")
        except Exception as e:
            _log(f"[ERROR] _poll_manual_command: {e}")
            # Clean up command file to prevent retry loops
            try:
                os.remove(MANUAL_COMMAND_PATH)
            except Exception:
                pass

    def _load_pnl_ledger(self) -> dict:
        try:
            if os.path.isfile(PNL_LEDGER_PATH):
                with open(PNL_LEDGER_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f) or {}
                if not isinstance(data, dict):
                    data = {}
                # Back-compat upgrades
                data.setdefault("total_realized_profit_usd", 0.0)
                data.setdefault("last_updated_ts", time.time())
                data.setdefault("open_positions", {})   # { "BTC": {"usd_cost": float, "qty": float} }
                data.setdefault("pending_orders", {})   # { "<order_id>": {...} }
                return data
        except Exception:
            pass
        return {
            "total_realized_profit_usd": 0.0,
            "last_updated_ts": time.time(),
            "open_positions": {},
            "pending_orders": {},
        }

    def _save_pnl_ledger(self) -> None:
        try:
            self._pnl_ledger["last_updated_ts"] = time.time()
            self._atomic_write_json(PNL_LEDGER_PATH, self._pnl_ledger)
        except Exception:
            pass

    def _trade_history_has_order_id(self, order_id: str) -> bool:
        try:
            if not order_id:
                return False
            if not os.path.isfile(TRADE_HISTORY_PATH):
                return False
            with open(TRADE_HISTORY_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    line = (line or "").strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue
                    if str(obj.get("order_id", "")).strip() == str(order_id).strip():
                        return True
        except Exception:
            return False
        return False

    def _get_buying_power(self) -> float:
        try:
            acct = self.get_account()
            if isinstance(acct, dict):
                return float(acct.get("buying_power", 0.0) or 0.0)
        except Exception:
            pass
        return 0.0

    # NOTE: get_order(), get_fills() removed — they hang indefinitely for certain
    # order IDs regardless of SDK timeout. See commit history for details.

    def _reconcile_pending_orders(self) -> None:
        """Clear any stale pending orders on startup.
        We no longer poll get_order() (it hangs indefinitely for certain IDs).
        Market orders fill instantly, so any pending entries are stale leftovers."""
        try:
            pending = self._pnl_ledger.get("pending_orders", {})
            if not isinstance(pending, dict) or not pending:
                _log("[RECONCILE] No pending orders to reconcile.")
                return

            _log(f"[RECONCILE] Clearing {len(pending)} stale pending order(s)...")
            for order_id, info in list(pending.items()):
                symbol = str(info.get("symbol", ""))
                side = str(info.get("side", ""))
                _log(f"[RECONCILE]   Cleared {side} {symbol} order {order_id[:12]}...")

            self._pnl_ledger["pending_orders"] = {}
            self._save_pnl_ledger()
            _log("[RECONCILE] Done.")
        except Exception:
            pass

    def _record_trade(
        self,
        side: str,
        symbol: str,
        qty: float,
        price: Optional[float] = None,
        avg_cost_basis: Optional[float] = None,
        pnl_pct: Optional[float] = None,
        tag: Optional[str] = None,
        order_id: Optional[str] = None,
        fees_usd: Optional[float] = None,
        buying_power_before: Optional[float] = None,
        buying_power_after: Optional[float] = None,
        buying_power_delta: Optional[float] = None,
    ) -> None:
        """
        Minimal local ledger for GUI:
        - append trade_history.jsonl
        - update pnl_ledger.json on sells (now using buying power delta when available)
        - persist per-coin open position cost (USD) so realized profit is exact
        """
        ts = time.time()

        side_l = str(side or "").lower().strip()
        base = str(symbol or "").upper().split("-")[0].strip()

        # Ensure ledger keys exist (back-compat)
        try:
            if not isinstance(self._pnl_ledger, dict):
                self._pnl_ledger = {}
            self._pnl_ledger.setdefault("total_realized_profit_usd", 0.0)
            self._pnl_ledger.setdefault("open_positions", {})
            self._pnl_ledger.setdefault("pending_orders", {})
        except Exception:
            pass

        realized = None
        position_cost_used = None
        position_cost_after = None

        # --- Exact USD-based accounting (your design) ---
        if base and (buying_power_delta is not None):
            try:
                bp_delta = float(buying_power_delta)
            except Exception:
                bp_delta = None

            if bp_delta is not None:
                try:
                    open_pos = self._pnl_ledger.get("open_positions", {})
                    if not isinstance(open_pos, dict):
                        open_pos = {}
                        self._pnl_ledger["open_positions"] = open_pos

                    pos = open_pos.get(base, None)
                    if not isinstance(pos, dict):
                        pos = {"usd_cost": 0.0, "qty": 0.0}
                        open_pos[base] = pos

                    pos_usd_cost = float(pos.get("usd_cost", 0.0) or 0.0)
                    pos_qty = float(pos.get("qty", 0.0) or 0.0)

                    q = float(qty or 0.0)

                    if side_l == "buy":
                        usd_used = -bp_delta  # buying power drops on buys
                        if usd_used < 0.0:
                            usd_used = 0.0

                        pos["usd_cost"] = float(pos_usd_cost) + float(usd_used)
                        pos["qty"] = float(pos_qty) + float(q if q > 0.0 else 0.0)

                        position_cost_after = float(pos["usd_cost"])

                        # Save because open position changed (needs to persist across restarts)
                        self._save_pnl_ledger()

                    elif side_l == "sell":
                        usd_got = bp_delta  # buying power rises on sells
                        if usd_got < 0.0:
                            usd_got = 0.0

                        # If partial sell ever happens, allocate cost pro-rata by qty.
                        if pos_qty > 0.0 and q > 0.0:
                            frac = min(1.0, float(q) / float(pos_qty))
                        else:
                            frac = 1.0

                        cost_used = float(pos_usd_cost) * float(frac)
                        pos["usd_cost"] = float(pos_usd_cost) - float(cost_used)
                        pos["qty"] = float(pos_qty) - float(q if q > 0.0 else 0.0)

                        position_cost_used = float(cost_used)
                        position_cost_after = float(pos.get("usd_cost", 0.0) or 0.0)

                        realized = float(usd_got) - float(cost_used)
                        self._pnl_ledger["total_realized_profit_usd"] = float(self._pnl_ledger.get("total_realized_profit_usd", 0.0) or 0.0) + float(realized)

                        # Clean up tiny dust
                        if float(pos.get("qty", 0.0) or 0.0) <= 1e-12 or float(pos.get("usd_cost", 0.0) or 0.0) <= 1e-6:
                            open_pos.pop(base, None)

                        self._save_pnl_ledger()

                except Exception as e:
                    _log(f"[ERROR] _record_trade P&L calc (bp_delta): {e}")

        # --- Fallback (old behavior) if we couldn't compute from buying power ---
        if realized is None and side_l == "sell" and price is not None and avg_cost_basis is not None:
            try:
                fee_val = float(fees_usd) if fees_usd is not None else 0.0
                realized = (float(price) - float(avg_cost_basis)) * float(qty) - fee_val
                self._pnl_ledger["total_realized_profit_usd"] = float(self._pnl_ledger.get("total_realized_profit_usd", 0.0)) + float(realized)
                self._save_pnl_ledger()
            except Exception as e:
                _log(f"[ERROR] _record_trade P&L calc (fallback): {e}")
                realized = None

        entry = {
            "ts": ts,
            "side": side,
            "tag": tag,
            "symbol": symbol,
            "qty": qty,
            "price": price,
            "avg_cost_basis": avg_cost_basis,
            "pnl_pct": pnl_pct,
            "fees_usd": fees_usd,
            "realized_profit_usd": realized,
            "order_id": order_id,
            "buying_power_before": float(buying_power_before) if buying_power_before is not None else None,
            "buying_power_after": float(buying_power_after) if buying_power_after is not None else None,
            "buying_power_delta": float(buying_power_delta) if buying_power_delta is not None else None,
            "position_cost_used_usd": float(position_cost_used) if position_cost_used is not None else None,
            "position_cost_after_usd": float(position_cost_after) if position_cost_after is not None else None,
        }
        self._append_jsonl(TRADE_HISTORY_PATH, entry)




    def _write_trader_status(self, status: dict) -> None:
        self._atomic_write_json(TRADER_STATUS_PATH, status)

    @staticmethod
    def _fmt_price(price: float) -> str:
        """
        Dynamic decimal formatting by magnitude:
        - >= 1.0   -> 2 decimals (BTC/ETH/etc won't show 8 decimals)
        - <  1.0   -> enough decimals to show meaningful digits (based on first non-zero),
                     then trim trailing zeros.
        """
        try:
            p = float(price)
        except Exception:
            return "N/A"

        if p == 0:
            return "0"

        ap = abs(p)

        if ap >= 1.0:
            decimals = 2
        else:
            # Example:
            # 0.5      -> decimals ~ 4 (prints "0.5" after trimming zeros)
            # 0.05     -> 5
            # 0.005    -> 6
            # 0.000012 -> 8
            decimals = int(-math.floor(math.log10(ap))) + 3
            decimals = max(2, min(12, decimals))

        s = f"{p:.{decimals}f}"

        # Trim useless trailing zeros for cleaner output (0.5000 -> 0.5)
        if "." in s:
            s = s.rstrip("0").rstrip(".")

        return s


    @staticmethod
    def _read_long_dca_signal(symbol: str) -> int:
        """
        Reads long_dca_signal.txt from the per-coin folder (same folder rules as trader.py).

        Used for:
        - Start gate: start trades at level 3+
        - DCA assist: levels 4-7 map to trader DCA stages 0-3 (trade starts at level 3 => stage 0)
        """
        sym = str(symbol).upper().strip()
        folder = base_paths.get(sym, main_dir if sym == "BTC" else os.path.join(main_dir, sym))
        path = os.path.join(folder, "long_dca_signal.txt")
        try:
            with open(path, "r") as f:
                raw = f.read().strip()
            val = int(float(raw))
            return val
        except Exception:
            return 0


    @staticmethod
    def _read_short_dca_signal(symbol: str) -> int:
        """
        Reads short_dca_signal.txt from the per-coin folder (same folder rules as trader.py).

        Used for:
        - Start gate: start trades at level 3+
        - DCA assist: levels 4-7 map to trader DCA stages 0-3 (trade starts at level 3 => stage 0)
        """
        sym = str(symbol).upper().strip()
        folder = base_paths.get(sym, main_dir if sym == "BTC" else os.path.join(main_dir, sym))
        path = os.path.join(folder, "short_dca_signal.txt")
        try:
            with open(path, "r") as f:
                raw = f.read().strip()
            val = int(float(raw))
            return val
        except Exception:
            return 0

    @staticmethod
    def _read_long_price_levels(symbol: str) -> list:
        """
        Reads low_bound_prices.html from the per-coin folder and returns a list of LONG (blue) price levels.

        Returned ordering is highest->lowest so:
          N1 = 1st blue line (top)
          ...
          N7 = 7th blue line (bottom)
        """
        sym = str(symbol).upper().strip()
        folder = base_paths.get(sym, main_dir if sym == "BTC" else os.path.join(main_dir, sym))
        path = os.path.join(folder, "low_bound_prices.html")
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = (f.read() or "").strip()
            if not raw:
                return []

            # Normalize common formats: python-list, comma-separated, newline-separated
            raw = raw.strip().strip("[]()")
            raw = raw.replace(",", " ").replace(";", " ").replace("|", " ")
            raw = raw.replace("\n", " ").replace("\t", " ")
            parts = [p for p in raw.split() if p]

            vals = []
            for p in parts:
                try:
                    vals.append(float(p))
                except Exception:
                    continue

            # De-dupe, then sort high->low for stable N1..N7 mapping
            out = []
            seen = set()
            for v in vals:
                k = round(float(v), 12)
                if k in seen:
                    continue
                seen.add(k)
                out.append(float(v))
            out.sort(reverse=True)
            return out
        except Exception:
            return []



    def initialize_dca_levels(self):

        """
        Initializes the DCA levels_triggered dictionary based on the number of buy orders
        that have occurred after the first buy order following the most recent sell order
        for each cryptocurrency.
        """
        holdings = self.get_bot_holdings()
        if not holdings or "results" not in holdings:
            _log("No holdings found. Skipping DCA levels initialization.")
            return

        for holding in holdings.get("results", []):
            symbol = holding["asset_code"]

            full_symbol = f"{symbol}-USD"
            orders = self.get_orders(full_symbol)
            
            if not orders or "results" not in orders:
                _log(f"No orders found for {full_symbol}. Skipping.")
                continue

            # Filter for filled buy and sell orders
            filled_orders = [
                order for order in orders["results"]
                if order["state"] == "filled" and order["side"] in ["buy", "sell"]
            ]
            
            if not filled_orders:
                _log(f"No filled buy or sell orders for {full_symbol}. Skipping.")
                continue

            # Sort orders by creation time in ascending order (oldest first)
            filled_orders.sort(key=lambda x: x["created_at"])

            # Find the timestamp of the most recent sell order
            most_recent_sell_time = None
            for order in reversed(filled_orders):
                if order["side"] == "sell":
                    most_recent_sell_time = order["created_at"]
                    break

            # Determine the cutoff time for buy orders
            if most_recent_sell_time:
                # Find all buy orders after the most recent sell
                relevant_buy_orders = [
                    order for order in filled_orders
                    if order["side"] == "buy" and order["created_at"] > most_recent_sell_time
                ]
                if not relevant_buy_orders:
                    _log(f"No buy orders after the most recent sell for {full_symbol}.")
                    self.dca_levels_triggered[symbol] = []
                    continue
                _log(f"Most recent sell for {full_symbol} at {most_recent_sell_time}.")
            else:
                # If no sell orders, consider all buy orders
                relevant_buy_orders = [
                    order for order in filled_orders
                    if order["side"] == "buy"
                ]
                if not relevant_buy_orders:
                    _log(f"No buy orders for {full_symbol}. Skipping.")
                    self.dca_levels_triggered[symbol] = []
                    continue
                _log(f"No sell orders found for {full_symbol}. Considering all buy orders.")

            # Ensure buy orders are sorted by creation time ascending
            relevant_buy_orders.sort(key=lambda x: x["created_at"])

            # Identify the first buy order in the relevant list
            first_buy_order = relevant_buy_orders[0]
            first_buy_time = first_buy_order["created_at"]

            # Count the number of buy orders after the first buy
            buy_orders_after_first = [
                order for order in relevant_buy_orders
                if order["created_at"] > first_buy_time
            ]

            triggered_levels_count = len(buy_orders_after_first)

            # Track DCA by stage index (0, 1, 2, ...) rather than % values.
            # This makes neural-vs-hardcoded clean, and allows repeating the -50% stage indefinitely.
            self.dca_levels_triggered[symbol] = list(range(triggered_levels_count))
            _log(f"Initialized DCA stages for {symbol}: {triggered_levels_count}")


    def _seed_dca_window_from_history(self) -> None:
        """
        Seeds in-memory DCA buy timestamps from TRADE_HISTORY_PATH so the 24h limit
        works across restarts.

        Uses the local GUI trade history (tag == "DCA") and resets per trade at the most recent sell.
        """
        now_ts = time.time()
        cutoff = now_ts - float(getattr(self, "dca_window_seconds", 86400))

        self._dca_buy_ts = {}
        self._dca_last_sell_ts = {}

        if not os.path.isfile(TRADE_HISTORY_PATH):
            return

        try:
            with open(TRADE_HISTORY_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    line = (line or "").strip()
                    if not line:
                        continue

                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue

                    ts = obj.get("ts", None)
                    side = str(obj.get("side", "")).lower()
                    tag = obj.get("tag", None)
                    sym_full = str(obj.get("symbol", "")).upper().strip()
                    base = sym_full.split("-")[0].strip() if sym_full else ""
                    if not base:
                        continue

                    try:
                        ts_f = float(ts)
                    except Exception:
                        continue

                    if side == "sell":
                        prev = float(self._dca_last_sell_ts.get(base, 0.0) or 0.0)
                        if ts_f > prev:
                            self._dca_last_sell_ts[base] = ts_f

                    elif side == "buy" and tag == "DCA":
                        self._dca_buy_ts.setdefault(base, []).append(ts_f)

        except Exception:
            return

        # Keep only DCA buys after the last sell (current trade) and within rolling 24h
        for base, ts_list in list(self._dca_buy_ts.items()):
            last_sell = float(self._dca_last_sell_ts.get(base, 0.0) or 0.0)
            kept = [t for t in ts_list if (t > last_sell) and (t >= cutoff)]
            kept.sort()
            self._dca_buy_ts[base] = kept


    def _dca_window_count(self, base_symbol: str, now_ts: Optional[float] = None) -> int:
        """
        Count of DCA buys for this coin within rolling 24h in the *current trade*.
        Current trade boundary = most recent sell we observed for this coin.
        """
        base = str(base_symbol).upper().strip()
        if not base:
            return 0

        now = float(now_ts if now_ts is not None else time.time())
        cutoff = now - float(getattr(self, "dca_window_seconds", 86400))
        last_sell = float(self._dca_last_sell_ts.get(base, 0.0) or 0.0)

        ts_list = list(self._dca_buy_ts.get(base, []) or [])
        ts_list = [t for t in ts_list if (t > last_sell) and (t >= cutoff)]
        self._dca_buy_ts[base] = ts_list
        return len(ts_list)


    def _note_dca_buy(self, base_symbol: str, ts: Optional[float] = None) -> None:
        base = str(base_symbol).upper().strip()
        if not base:
            return
        t = float(ts if ts is not None else time.time())
        self._dca_buy_ts.setdefault(base, []).append(t)
        self._dca_window_count(base, now_ts=t)  # prune in-place


    def _reset_dca_window_for_trade(self, base_symbol: str, sold: bool = False, ts: Optional[float] = None) -> None:
        base = str(base_symbol).upper().strip()
        if not base:
            return
        if sold:
            self._dca_last_sell_ts[base] = float(ts if ts is not None else time.time())
        self._dca_buy_ts[base] = []


    def get_account(self) -> Any:
        """Returns dict with 'buying_power' key (USD available balance)."""
        try:
            resp = self.client.get_accounts()
            accounts = resp["accounts"]
            for acct in accounts:
                if str(acct["currency"]).upper() == "USD":
                    val = acct["available_balance"]["value"]
                    return {"buying_power": float(val)}
            return {"buying_power": 0.0}
        except Exception as e:
            _log(f"[ERROR] get_account: {e}")
            return None

    def get_holdings(self) -> Any:
        """Returns dict with 'results' list of {'asset_code': str, 'total_quantity': str}."""
        try:
            resp = self.client.get_accounts()
            accounts = resp["accounts"]
            results = []
            for acct in accounts:
                currency = str(acct["currency"]).upper()
                val = float(acct["available_balance"]["value"])
                if currency != "USD" and val > 0:
                    results.append({
                        "asset_code": currency,
                        "total_quantity": str(val),
                    })
            return {"results": results}
        except Exception as e:
            _log(f"[ERROR] get_holdings: {e}")
            return None

    def get_bot_holdings(self) -> Any:
        """Returns holdings filtered to only coins in crypto_symbols (bot-managed coins)."""
        all_holdings = self.get_holdings()
        if not all_holdings or "results" not in all_holdings:
            return all_holdings
        filtered = [
            h for h in all_holdings.get("results", [])
            if str(h.get("asset_code", "")).upper() in crypto_symbols
        ]
        return {"results": filtered}

    def get_trading_pairs(self) -> Any:
        try:
            resp = self.client.get_products(product_type="SPOT")
            return list(resp["products"])
        except Exception as e:
            _log(f"[ERROR] get_trading_pairs: {e}")
            return []

    def get_orders(self, symbol: str) -> Any:
        """Returns dict with 'results' list of normalized order dicts."""
        try:
            resp = self.client.list_orders(product_ids=[symbol])
            raw_orders = resp["orders"]
            results = []
            for o in raw_orders:
                # SDK returns Order objects, not dicts — use [] with try/except for optional fields
                oid = str(o["order_id"])
                status = str(o["status"]).lower()
                side = str(o["side"]).lower()
                created = str(o["created_time"])
                try:
                    filled_size = str(o["filled_size"] or "0")
                except (KeyError, TypeError):
                    filled_size = "0"
                try:
                    avg_price = str(o["average_filled_price"] or "0")
                except (KeyError, TypeError):
                    avg_price = "0"
                try:
                    total_fees = str(o["total_fees"] or "0")
                except (KeyError, TypeError):
                    total_fees = "0"

                # Normalize Coinbase status to internal state format
                state_map = {"filled": "filled", "cancelled": "canceled", "canceled": "canceled",
                             "expired": "canceled", "failed": "failed", "pending": "pending",
                             "open": "pending"}
                state = state_map.get(status, status)

                # Build executions list from fill data
                executions = []
                try:
                    fq = float(filled_size)
                    fp = float(avg_price)
                    if fq > 0 and fp > 0:
                        executions.append({"quantity": fq, "effective_price": fp})
                except Exception:
                    pass

                results.append({
                    "id": oid,
                    "side": side,
                    "state": state,
                    "created_at": created,
                    "executions": executions,
                    "filled_asset_quantity": filled_size,
                    "average_price": avg_price,
                    "total_fees": total_fees,
                })
            return {"results": results}
        except Exception as e:
            _log(f"[ERROR] get_orders({symbol}): {e}")
            return None

    def calculate_cost_basis(self):
        holdings = self.get_bot_holdings()
        if not holdings or "results" not in holdings:
            return {}

        active_assets = {holding["asset_code"] for holding in holdings.get("results", [])}
        current_quantities = {
            holding["asset_code"]: float(holding["total_quantity"])
            for holding in holdings.get("results", [])
        }

        cost_basis = {}

        for asset_code in active_assets:
            orders = self.get_orders(f"{asset_code}-USD")
            if not orders or "results" not in orders:
                continue

            # Get all filled buy orders, sorted from most recent to oldest
            buy_orders = [
                order for order in orders["results"]
                if order["side"] == "buy" and order["state"] == "filled"
            ]
            buy_orders.sort(key=lambda x: x["created_at"], reverse=True)

            remaining_quantity = current_quantities[asset_code]
            total_cost = 0.0

            for order in buy_orders:
                for execution in order.get("executions", []):
                    quantity = float(execution["quantity"])
                    price = float(execution["effective_price"])

                    if remaining_quantity <= 0:
                        break

                    # Use only the portion of the quantity needed to match the current holdings
                    if quantity > remaining_quantity:
                        total_cost += remaining_quantity * price
                        remaining_quantity = 0
                    else:
                        total_cost += quantity * price
                        remaining_quantity -= quantity

                if remaining_quantity <= 0:
                    break

            if current_quantities[asset_code] > 0:
                # If order history can't account for the full holding (e.g. transferred in
                # or bought before API history), treat unaccounted qty at current market price
                # so P&L shows breakeven instead of a misleading 28000% gain.
                if remaining_quantity > 0:
                    try:
                        buy_prices, _, _ = self.get_price([f"{asset_code}-USD"])
                        fallback_price = buy_prices.get(f"{asset_code}-USD", 0.0)
                        if fallback_price > 0:
                            total_cost += remaining_quantity * fallback_price
                    except Exception:
                        pass
                cost_basis[asset_code] = total_cost / current_quantities[asset_code]
            else:
                cost_basis[asset_code] = 0.0

        return cost_basis

    def get_price(self, symbols: list) -> Dict[str, float]:
        buy_prices = {}
        sell_prices = {}
        valid_symbols = []

        query_symbols = [s for s in symbols if s != "USDC-USD"]
        if not query_symbols:
            return buy_prices, sell_prices, valid_symbols

        try:
            resp = self.client.get_best_bid_ask(product_ids=query_symbols)
            pricebooks = resp["pricebooks"]
        except Exception as e:
            _log(f"[ERROR] get_price: {e}")
            pricebooks = []

        fetched = set()
        for pb in pricebooks:
            try:
                product_id = str(pb["product_id"])
                bids = pb["bids"]
                asks = pb["asks"]

                if not bids or not asks:
                    continue

                bid = float(bids[0]["price"])
                ask = float(asks[0]["price"])

                if ask > 0 and bid > 0:
                    buy_prices[product_id] = ask
                    sell_prices[product_id] = bid
                    valid_symbols.append(product_id)
                    fetched.add(product_id)
                    try:
                        self._last_good_bid_ask[product_id] = {"ask": ask, "bid": bid, "ts": time.time()}
                    except Exception:
                        pass
            except Exception:
                continue

        # Fallback to cached bid/ask for symbols not fetched
        for symbol in query_symbols:
            if symbol not in fetched:
                cached = None
                try:
                    cached = self._last_good_bid_ask.get(symbol)
                except Exception:
                    cached = None
                if cached:
                    ask = float(cached.get("ask", 0.0) or 0.0)
                    bid = float(cached.get("bid", 0.0) or 0.0)
                    if ask > 0.0 and bid > 0.0:
                        buy_prices[symbol] = ask
                        sell_prices[symbol] = bid
                        valid_symbols.append(symbol)

        return buy_prices, sell_prices, valid_symbols


    def place_buy_order(
        self,
        client_order_id: str,
        side: str,
        order_type: str,
        symbol: str,
        amount_in_usd: float,
        avg_cost_basis: Optional[float] = None,
        pnl_pct: Optional[float] = None,
        tag: Optional[str] = None,
    ) -> Any:
        try:
            buying_power_before = self._get_buying_power()

            resp = self.client.market_order_buy(
                client_order_id=client_order_id,
                product_id=symbol,
                quote_size=str(round(amount_in_usd, 2)),
            )

            success = resp["success"]
            sr = resp["success_response"]
            order_id = sr["order_id"] if sr else None

            if not success or not order_id:
                return None

            _log(f"[BUY] Market order placed: {symbol} ${amount_in_usd:.2f} (order {order_id[:12]}...)")

            # Market orders fill instantly on Coinbase — no need to poll get_order()
            # (get_order hangs indefinitely for certain order IDs, cooking the CPU)
            # Use current ask price as fill price estimate, buying power delta for actual cost
            time.sleep(2)  # brief pause for settlement
            buying_power_after = self._get_buying_power()
            buying_power_delta = float(buying_power_after) - float(buying_power_before)

            # Estimate fill price from current market price
            try:
                buy_prices, _, _ = self.get_price([symbol])
                fill_price = buy_prices.get(symbol, 0.0)
            except Exception:
                fill_price = 0.0

            # Buy bp_delta should be negative (spending money). If near-zero or positive,
            # Coinbase hasn't settled — estimate from order amount.
            if buying_power_delta > -0.01:
                buying_power_delta = -amount_in_usd

            fill_qty = abs(buying_power_delta) / fill_price if fill_price > 0 else (amount_in_usd / fill_price if fill_price > 0 else 0.0)

            self._record_trade(
                side="buy",
                symbol=symbol,
                qty=float(fill_qty),
                price=float(fill_price),
                avg_cost_basis=float(avg_cost_basis) if avg_cost_basis is not None else None,
                pnl_pct=float(pnl_pct) if pnl_pct is not None else None,
                tag=tag,
                order_id=order_id,
                buying_power_before=buying_power_before,
                buying_power_after=buying_power_after,
                buying_power_delta=buying_power_delta,
            )

            return {"id": order_id, "success": True}

        except Exception as e:
            _log(f"[ERROR] place_buy_order({symbol}): {e}")
            _log(traceback.format_exc())

        return None



    def place_sell_order(
        self,
        client_order_id: str,
        side: str,
        order_type: str,
        symbol: str,
        asset_quantity: float,
        expected_price: Optional[float] = None,
        avg_cost_basis: Optional[float] = None,
        pnl_pct: Optional[float] = None,
        tag: Optional[str] = None,
    ) -> Any:
        response = None
        try:
            buying_power_before = self._get_buying_power()

            resp = self.client.market_order_sell(
                client_order_id=client_order_id,
                product_id=symbol,
                base_size=str(asset_quantity),
            )

            success = resp["success"]
            sr = resp["success_response"]
            order_id = sr["order_id"] if sr else None

            if not success or not order_id:
                return None

            response = {"id": order_id, "success": True}
            _log(f"[SELL] Market order placed: {symbol} qty={asset_quantity} (order {order_id[:12]}...)")

            # Market orders fill instantly — no polling get_order() (it hangs)
            # Use current bid price and buying power delta for actual P&L
            time.sleep(2)  # brief pause for settlement

            actual_qty = float(asset_quantity)
            try:
                _, sell_prices, _ = self.get_price([symbol])
                actual_price = sell_prices.get(symbol, 0.0)
            except Exception:
                actual_price = float(expected_price) if expected_price is not None else 0.0

            if avg_cost_basis is not None and actual_price > 0:
                try:
                    acb = float(avg_cost_basis)
                    if acb > 0:
                        pnl_pct = ((float(actual_price) - acb) / acb) * 100.0
                except Exception:
                    pass

            buying_power_after = self._get_buying_power()
            buying_power_delta = float(buying_power_after) - float(buying_power_before)

            # Sell bp_delta should be positive (receiving money). If near-zero or negative,
            # Coinbase hasn't settled — estimate from qty * price.
            if buying_power_delta < 0.01 and actual_price > 0:
                buying_power_delta = float(actual_qty) * float(actual_price)

            self._record_trade(
                side="sell",
                symbol=symbol,
                qty=float(actual_qty),
                price=float(actual_price) if actual_price is not None else None,
                avg_cost_basis=float(avg_cost_basis) if avg_cost_basis is not None else None,
                pnl_pct=float(pnl_pct) if pnl_pct is not None else None,
                tag=tag,
                order_id=order_id,
                fees_usd=None,  # can't get fills without get_fills() (hangs)
                buying_power_before=buying_power_before,
                buying_power_after=buying_power_after,
                buying_power_delta=buying_power_delta,
            )

            try:
                self._pnl_ledger.get("pending_orders", {}).pop(order_id, None)
                self._save_pnl_ledger()
            except Exception:
                pass

        except Exception as e:
            _log(f"[ERROR] place_sell_order({symbol}): {e}")
            _log(traceback.format_exc())

        return response






    def manage_trades(self):
        trades_made = False  # Flag to track if any trade was made in this iteration

        # Rotate signal log and poll for manual commands
        self._rotate_signal_log()
        self._poll_manual_command()

        # Hot-reload coins list + paths + trade params from GUI settings while running
        try:
            _refresh_paths_and_symbols()
            self.path_map = dict(base_paths)
            self.dca_levels = list(DCA_LEVELS)
            self.max_dca_buys_per_24h = int(MAX_DCA_BUYS_PER_24H)
            self.dca_cooldown_minutes = int(DCA_COOLDOWN_MINUTES)

            # Trailing PM settings (hot-reload)
            old_sig = getattr(self, "_last_trailing_settings_sig", None)

            new_gap = float(TRAILING_GAP_PCT)
            new_pm0 = float(PM_START_PCT_NO_DCA)
            new_pm1 = float(PM_START_PCT_WITH_DCA)

            self.trailing_gap_pct = new_gap
            self.pm_start_pct_no_dca = new_pm0
            self.pm_start_pct_with_dca = new_pm1

            new_sig = (float(new_gap), float(new_pm0), float(new_pm1))

            # If trailing settings changed, reset ALL trailing PM state so:
            # - the line updates immediately
            # - peak/armed/was_above are cleared
            if (old_sig is not None) and (new_sig != old_sig):
                self.trailing_pm = {}

            self._last_trailing_settings_sig = new_sig
        except Exception:
            pass




        # Fetch account details
        account = self.get_account()
        # Fetch holdings
        holdings = self.get_holdings()
        # Fetch trading pairs
        trading_pairs = self.get_trading_pairs()

        # Use the stored cost_basis instead of recalculating
        cost_basis = self.cost_basis
        # Fetch current prices
        symbols = [holding["asset_code"] + "-USD" for holding in holdings.get("results", [])]

        # ALSO fetch prices for tracked coins even if not currently held (so GUI can show bid/ask lines)
        for s in crypto_symbols:
            full = f"{s}-USD"
            if full not in symbols:
                symbols.append(full)

        current_buy_prices, current_sell_prices, valid_symbols = self.get_price(symbols)

        # Calculate total account value (robust: never drop a held coin to $0 on transient API misses)
        snapshot_ok = True

        # buying power
        try:
            buying_power = float(account.get("buying_power", 0))
        except Exception:
            buying_power = 0.0
            snapshot_ok = False

        # holdings list (treat missing/invalid holdings payload as transient error)
        try:
            holdings_list = holdings.get("results", None) if isinstance(holdings, dict) else None
            if not isinstance(holdings_list, list):
                holdings_list = []
                snapshot_ok = False
        except Exception:
            holdings_list = []
            snapshot_ok = False

        holdings_buy_value = 0.0
        holdings_sell_value = 0.0

        for holding in holdings_list:
            try:
                asset = holding.get("asset_code")
                if asset == "USDC":
                    continue

                qty = float(holding.get("total_quantity", 0.0))
                if qty <= 0.0:
                    continue

                sym = f"{asset}-USD"
                bp = float(current_buy_prices.get(sym, 0.0) or 0.0)
                sp = float(current_sell_prices.get(sym, 0.0) or 0.0)

                # If any held asset is missing a usable price this tick, do NOT allow a new "low" snapshot
                if bp <= 0.0 or sp <= 0.0:
                    snapshot_ok = False
                    continue

                holdings_buy_value += qty * bp
                holdings_sell_value += qty * sp
            except Exception as e:
                _log(f"[ERROR] per-holding calc: {e}")
                snapshot_ok = False
                continue

        total_account_value = buying_power + holdings_sell_value
        in_use = (holdings_sell_value / total_account_value) * 100 if total_account_value > 0 else 0.0

        # If this tick is incomplete, fall back to last known-good snapshot so the GUI chart never gets a bogus dip.
        if (not snapshot_ok) or (total_account_value <= 0.0):
            last = getattr(self, "_last_good_account_snapshot", None) or {}
            if last.get("total_account_value") is not None:
                total_account_value = float(last["total_account_value"])
                buying_power = float(last.get("buying_power", buying_power or 0.0))
                holdings_sell_value = float(last.get("holdings_sell_value", holdings_sell_value or 0.0))
                holdings_buy_value = float(last.get("holdings_buy_value", holdings_buy_value or 0.0))
                in_use = float(last.get("percent_in_trade", in_use or 0.0))
        else:
            # Save last complete snapshot
            self._last_good_account_snapshot = {
                "total_account_value": float(total_account_value),
                "buying_power": float(buying_power),
                "holdings_sell_value": float(holdings_sell_value),
                "holdings_buy_value": float(holdings_buy_value),
                "percent_in_trade": float(in_use),
            }

        os.system('cls' if os.name == 'nt' else 'clear')
        _log(f"Acct ${total_account_value:.2f} | hold ${holdings_sell_value:.2f} ({in_use:.0f}%) | PM +{self.pm_start_pct_no_dca:.1f}/+{self.pm_start_pct_with_dca:.1f}% gap {self.trailing_gap_pct:.1f}%")

        positions = {}
        for holding in holdings.get("results", []):
            symbol = holding["asset_code"]
            full_symbol = f"{symbol}-USD"

            if full_symbol not in valid_symbols or symbol == "USDC":
                continue

            quantity = float(holding["total_quantity"])
            current_buy_price = current_buy_prices.get(full_symbol, 0)
            current_sell_price = current_sell_prices.get(full_symbol, 0)
            avg_cost_basis = cost_basis.get(symbol, 0)

            # Skip pre-existing holdings that the bot did not buy (no cost basis on record)
            if avg_cost_basis <= 0:
                continue

            gain_loss_percentage_buy = ((current_buy_price - avg_cost_basis) / avg_cost_basis) * 100
            gain_loss_percentage_sell = ((current_sell_price - avg_cost_basis) / avg_cost_basis) * 100

            value = quantity * current_sell_price
            triggered_levels_count = len(self.dca_levels_triggered.get(symbol, []))
            triggered_levels = triggered_levels_count  # Number of DCA levels triggered

            # Determine the next DCA trigger for this coin (hardcoded % and optional neural level)
            next_stage = triggered_levels_count  # stage 0 == first DCA after entry (trade starts at neural level 3)

            # Hardcoded % for this stage (repeat -50% after we reach it)
            hard_next = self.dca_levels[next_stage] if next_stage < len(self.dca_levels) else self.dca_levels[-1]

            # Neural DCA applies to the levels BELOW the trade-start level.
            # Example: trade_start_level=3 => stages 0..3 map to N4..N7 (4 total).
            start_level = max(1, min(int(TRADE_START_LEVEL or 3), 7))
            neural_dca_max = max(0, 7 - start_level)

            if next_stage < neural_dca_max:
                neural_next = start_level + 1 + next_stage
                next_dca_display = f"{hard_next:.2f}% / N{neural_next}"
            else:
                next_dca_display = f"{hard_next:.2f}%"

            # --- DCA DISPLAY LINE (show whichever trigger will be hit first: higher of NEURAL line vs HARD line) ---
            # Hardcoded gives an actual price line: cost_basis * (1 + hard_next%).
            # Neural gives an actual price line from low_bound_prices.html (N1..N7).
            dca_line_source = "HARD"
            dca_line_price = 0.0
            dca_line_pct = 0.0

            if avg_cost_basis > 0:
                # Hardcoded trigger line price
                hard_line_price = avg_cost_basis * (1.0 + (hard_next / 100.0))

                # Default to hardcoded unless neural line is higher (hit first)
                dca_line_price = hard_line_price

                if next_stage < neural_dca_max:
                    neural_level_needed_disp = start_level + 1 + next_stage
                    neural_levels = self._read_long_price_levels(symbol)  # highest->lowest == N1..N7

                    neural_line_price = 0.0
                    if len(neural_levels) >= neural_level_needed_disp:
                        neural_line_price = float(neural_levels[neural_level_needed_disp - 1])

                    # Whichever is higher will be hit first as price drops
                    if neural_line_price > dca_line_price:
                        dca_line_price = neural_line_price
                        dca_line_source = f"NEURAL N{neural_level_needed_disp}"


                # PnL% shown alongside DCA is the normal buy-side PnL%
                # (same calculation as GUI "Buy Price PnL": current buy/ask vs avg cost basis)
                dca_line_pct = gain_loss_percentage_buy




            dca_line_price_disp = self._fmt_price(dca_line_price) if avg_cost_basis > 0 else "N/A"

            # Set color code:
            # - DCA is green if we're above the chosen DCA line, red if we're below it
            # - SELL stays based on profit vs cost basis (your original behavior)
            if dca_line_pct >= 0:
                color = Fore.GREEN
            else:
                color = Fore.RED

            if gain_loss_percentage_sell >= 0:
                color2 = Fore.GREEN
            else:
                color2 = Fore.RED

            # --- Trailing PM display (per-coin, isolated) ---
            # Display uses current state if present; otherwise shows the base PM start line.
            trail_status = "N/A"
            pm_start_pct_disp = 0.0
            base_pm_line_disp = 0.0
            trail_line_disp = 0.0
            trail_peak_disp = 0.0
            above_disp = False
            dist_to_trail_pct = 0.0

            if avg_cost_basis > 0:
                pm_start_pct_disp = self.pm_start_pct_no_dca if int(triggered_levels) == 0 else self.pm_start_pct_with_dca
                base_pm_line_disp = avg_cost_basis * (1.0 + (pm_start_pct_disp / 100.0))

                state = self.trailing_pm.get(symbol)
                if state is None:
                    trail_line_disp = base_pm_line_disp
                    trail_peak_disp = 0.0
                    active_disp = False
                else:
                    trail_line_disp = float(state.get("line", base_pm_line_disp))
                    trail_peak_disp = float(state.get("peak", 0.0))
                    active_disp = bool(state.get("active", False))

                above_disp = current_sell_price >= trail_line_disp
                # If we're already above the line, trailing is effectively "on/armed" (even if active flips this tick)
                trail_status = "ON" if (active_disp or above_disp) else "OFF"

                if trail_line_disp > 0:
                    dist_to_trail_pct = ((current_sell_price - trail_line_disp) / trail_line_disp) * 100.0
            file = open(symbol+'_current_price.txt', 'w+')
            file.write(str(current_buy_price))
            file.close()
            positions[symbol] = {
                "quantity": quantity,
                "avg_cost_basis": avg_cost_basis,
                "current_buy_price": current_buy_price,
                "current_sell_price": current_sell_price,
                "gain_loss_pct_buy": gain_loss_percentage_buy,
                "gain_loss_pct_sell": gain_loss_percentage_sell,
                "value_usd": value,
                "dca_triggered_stages": int(triggered_levels_count),
                "next_dca_display": next_dca_display,
                "dca_line_price": float(dca_line_price) if dca_line_price else 0.0,
                "dca_line_source": dca_line_source,
                "dca_line_pct": float(dca_line_pct) if dca_line_pct else 0.0,
                "trail_active": True if (trail_status == "ON") else False,
                "trail_line": float(trail_line_disp) if trail_line_disp else 0.0,
                "trail_peak": float(trail_peak_disp) if trail_peak_disp else 0.0,
                "dist_to_trail_pct": float(dist_to_trail_pct) if dist_to_trail_pct else 0.0,
            }


            _log(
                f"{symbol:>4} ${value:>8.2f}"
                f" | {color}{dca_line_pct:+.1f}%{Style.RESET_ALL} @ {self._fmt_price(current_buy_price)}"
                f" | sell {color2}{gain_loss_percentage_sell:.1f}%{Style.RESET_ALL}"
                f" | DCA {triggered_levels} next {next_dca_display}"
            )


            if avg_cost_basis > 0:
                _log(f"     trail {self._fmt_price(trail_line_disp)} {'ABOVE' if above_disp else 'below'} | line {dca_line_price_disp} {dca_line_source}")
            else:
                _log("     trail N/A (no cost basis)")



            # --- Trailing profit margin (0.5% trail gap) ---
            # PM "start line" is the normal 5% / 2.5% line (depending on DCA levels hit).
            # Trailing activates once price is ABOVE the PM start line, then line follows peaks up
            # by 0.5%. Forced sell happens ONLY when price goes from ABOVE the trailing line to BELOW it.
            if avg_cost_basis > 0:
                pm_start_pct = self.pm_start_pct_no_dca if int(triggered_levels) == 0 else self.pm_start_pct_with_dca
                base_pm_line = avg_cost_basis * (1.0 + (pm_start_pct / 100.0))
                trail_gap = self.trailing_gap_pct / 100.0  # 0.5% => 0.005

                # If trailing settings changed since this coin's state was created, reset it.
                settings_sig = (
                    float(self.trailing_gap_pct),
                    float(self.pm_start_pct_no_dca),
                    float(self.pm_start_pct_with_dca),
                )

                state = self.trailing_pm.get(symbol)
                if (state is None) or (state.get("settings_sig") != settings_sig):
                    state = {
                        "active": False,
                        "line": base_pm_line,
                        "peak": 0.0,
                        "was_above": False,
                        "settings_sig": settings_sig,
                    }
                    self.trailing_pm[symbol] = state
                else:
                    # Keep signature up to date
                    state["settings_sig"] = settings_sig

                    # IMPORTANT:
                    # If trailing hasn't activated yet, this is just the PM line.
                    # It MUST track the current avg_cost_basis (so it can move DOWN after each DCA).
                    if not state.get("active", False):
                        state["line"] = base_pm_line
                    else:
                        # Once trailing is active, the line should never be below the base PM start line.
                        if state.get("line", 0.0) < base_pm_line:
                            state["line"] = base_pm_line

                # Use SELL price because that's what you actually get when you market sell
                above_now = current_sell_price >= state["line"]

                # Activate trailing once we first get above the base PM line
                if (not state["active"]) and above_now:
                    state["active"] = True
                    state["peak"] = current_sell_price

                # If active, update peak and move trailing line up behind it
                if state["active"]:
                    if current_sell_price > state["peak"]:
                        state["peak"] = current_sell_price

                    new_line = state["peak"] * (1.0 - trail_gap)
                    if new_line < base_pm_line:
                        new_line = base_pm_line
                    if new_line > state["line"]:
                        state["line"] = new_line

                    # Forced sell on cross from ABOVE -> BELOW trailing line
                    if state["was_above"] and (current_sell_price < state["line"]):
                        self._log_signal(symbol, "TRAIL_SELL",
                            f"Price {current_sell_price:.8f} < trail line {state['line']:.8f}",
                            details={"sell_price": current_sell_price, "trail_line": state["line"],
                                     "pnl_pct": gain_loss_percentage_sell})
                        _log(
                            f"  Trailing PM hit for {symbol}. "
                            f"Sell price {current_sell_price:.8f} fell below trailing line {state['line']:.8f}."
                        )
                        response = self.place_sell_order(
                            str(uuid.uuid4()),
                            "sell",
                            "market",
                            full_symbol,
                            quantity,
                            expected_price=current_sell_price,
                            avg_cost_basis=avg_cost_basis,
                            pnl_pct=gain_loss_percentage_sell,
                            tag="TRAIL_SELL",
                        )

                        if response and isinstance(response, dict) and "errors" not in response:
                            trades_made = True
                            self.trailing_pm.pop(symbol, None)  # clear per-coin trailing state on exit

                            # Trade ended -> reset rolling 24h DCA window for this coin
                            self._reset_dca_window_for_trade(symbol, sold=True)

                            _log(f"  Successfully sold {quantity} {symbol}.")
                            time.sleep(5)
                            holdings = self.get_holdings()
                            continue


                # Save this tick’s position relative to the line (needed for “above -> below” detection)
                state["was_above"] = above_now



            # DCA (NEURAL or hardcoded %, whichever hits first for the current stage)
            # Trade starts at neural level 3 => trader is at stage 0.
            # Neural-driven DCA stages (max 4):
            #   stage 0 => neural 4 OR -2.5%
            #   stage 1 => neural 5 OR -5.0%
            #   stage 2 => neural 6 OR -10.0%
            #   stage 3 => neural 7 OR -20.0%
            # After that: hardcoded only (-30, -40, -50, then repeat -50 forever).
            current_stage = len(self.dca_levels_triggered.get(symbol, []))

            # Hardcoded loss % for this stage (repeat last level after list ends)
            hard_level = self.dca_levels[current_stage] if current_stage < len(self.dca_levels) else self.dca_levels[-1]
            hard_hit = gain_loss_percentage_buy <= hard_level

            # Neural trigger only for first 4 DCA stages
            neural_level_needed = None
            neural_level_now = None
            neural_hit = False
            if current_stage < 4:
                neural_level_needed = current_stage + 4
                neural_level_now = self._read_long_dca_signal(symbol)

                # Keep it sane: don't DCA from neural if we're not even below cost basis.
                neural_hit = (gain_loss_percentage_buy < 0) and (neural_level_now >= neural_level_needed)

            if hard_hit or neural_hit:
                if neural_hit and hard_hit:
                    reason = f"NEURAL L{neural_level_now}>=L{neural_level_needed} OR HARD {hard_level:.2f}%"
                elif neural_hit:
                    reason = f"NEURAL L{neural_level_now}>=L{neural_level_needed}"
                else:
                    reason = f"HARD {hard_level:.2f}%"

                _log(f"  DCAing {symbol} (stage {current_stage + 1}) via {reason}.")

                _log(f"  Current Value: ${value:.2f}")
                dca_amount = value * float(DCA_MULTIPLIER or 0.0)
                _log(f"  DCA Amount: ${dca_amount:.2f}")
                _log(f"  Buying Power: ${buying_power:.2f}")


                recent_dca = self._dca_window_count(symbol)
                cooldown_min = int(getattr(self, "dca_cooldown_minutes", 60))
                cooldown_ok = True
                if cooldown_min > 0:
                    last_ts_list = list(self._dca_buy_ts.get(symbol, []) or [])
                    if last_ts_list:
                        secs_since = time.time() - max(last_ts_list)
                        if secs_since < cooldown_min * 60:
                            cooldown_ok = False
                            mins_left = (cooldown_min * 60 - secs_since) / 60.0

                if recent_dca >= int(getattr(self, "max_dca_buys_per_24h", 2)):
                    self._log_signal(symbol, "DCA_SKIP", f"24h limit ({recent_dca}/{self.max_dca_buys_per_24h})",
                        details={"stage": current_stage, "reason": reason})
                    _log(
                        f"  Skipping DCA for {symbol}. "
                        f"Already placed {recent_dca} DCA buys in the last 24h (max {self.max_dca_buys_per_24h})."
                    )

                elif not cooldown_ok:
                    self._log_signal(symbol, "DCA_SKIP", f"Cooldown ({mins_left:.0f}m left of {cooldown_min}m)",
                        details={"stage": current_stage, "reason": reason})
                    _log(f"  Skipping DCA for {symbol}. Cooldown: {mins_left:.0f}m remaining (min {cooldown_min}m between buys).")

                elif dca_amount <= buying_power:
                    response = self.place_buy_order(
                        str(uuid.uuid4()),
                        "buy",
                        "market",
                        full_symbol,
                        dca_amount,
                        avg_cost_basis=avg_cost_basis,
                        pnl_pct=gain_loss_percentage_buy,
                        tag="DCA",
                    )

                    _log(f"  Buy Response: {response}")
                    if response and "errors" not in response:
                        # record that we completed THIS stage (no matter what triggered it)
                        self.dca_levels_triggered.setdefault(symbol, []).append(current_stage)

                        # Only record a DCA buy timestamp on success (so skips never advance anything)
                        self._note_dca_buy(symbol)

                        # DCA changes avg_cost_basis, so the PM line must be rebuilt from the new basis
                        # (this will re-init to 5% if DCA=0, or 2.5% if DCA>=1)
                        self.trailing_pm.pop(symbol, None)

                        trades_made = True
                        self._log_signal(symbol, "DCA", reason,
                            details={"stage": current_stage, "amount": dca_amount})
                        _log(f"  Successfully placed DCA buy order for {symbol}.")
                    else:
                        _log(f"  Failed to place DCA buy order for {symbol}.")

                else:
                    self._log_signal(symbol, "DCA_SKIP", f"Insufficient funds (need ${dca_amount:.2f}, have ${buying_power:.2f})",
                        details={"stage": current_stage})
                    _log(f"  Skipping DCA for {symbol}. Not enough funds.")

            else:
                self._log_signal(symbol, "HOLD",
                    f"PnL {gain_loss_percentage_buy:+.2f}% > DCA {hard_level:.2f}%",
                    details={"pnl_buy": gain_loss_percentage_buy, "hard_level": hard_level})


        # --- ensure GUI gets bid/ask lines even for coins not currently held ---
        try:
            for sym in crypto_symbols:
                if sym in positions:
                    continue

                full_symbol = f"{sym}-USD"
                if full_symbol not in valid_symbols or sym == "USDC":
                    continue

                current_buy_price = current_buy_prices.get(full_symbol, 0.0)
                current_sell_price = current_sell_prices.get(full_symbol, 0.0)

                # keep the per-coin current price file behavior for consistency
                try:
                    file = open(sym + '_current_price.txt', 'w+')
                    file.write(str(current_buy_price))
                    file.close()
                except Exception:
                    pass

                positions[sym] = {
                    "quantity": 0.0,
                    "avg_cost_basis": 0.0,
                    "current_buy_price": current_buy_price,
                    "current_sell_price": current_sell_price,
                    "gain_loss_pct_buy": 0.0,
                    "gain_loss_pct_sell": 0.0,
                    "value_usd": 0.0,
                    "dca_triggered_stages": int(len(self.dca_levels_triggered.get(sym, []))),
                    "next_dca_display": "",
                    "dca_line_price": 0.0,
                    "dca_line_source": "N/A",
                    "dca_line_pct": 0.0,
                    "trail_active": False,
                    "trail_line": 0.0,
                    "trail_peak": 0.0,
                    "dist_to_trail_pct": 0.0,
                }
        except Exception:
            pass

        if not trading_pairs:
            return



        alloc_pct = float(START_ALLOC_PCT or 0.005)
        allocation_in_usd = total_account_value * (alloc_pct / 100.0)
        if allocation_in_usd < 1.0:
            allocation_in_usd = 1.0  # Coinbase minimum market order is $1


        holding_full_symbols = [f"{h['asset_code']}-USD" for h in holdings.get("results", [])]

        start_index = 0
        while start_index < len(crypto_symbols):
            base_symbol = crypto_symbols[start_index].upper().strip()
            full_symbol = f"{base_symbol}-USD"

            # Skip if already held BY THE BOT (has cost basis). Pre-existing holdings are ignored.
            if full_symbol in holding_full_symbols and cost_basis.get(base_symbol, 0) > 0:
                start_index += 1
                continue

            # Neural signals are used as a "permission to start" gate.
            buy_count = self._read_long_dca_signal(base_symbol)
            sell_count = self._read_short_dca_signal(base_symbol)

            start_level = max(1, min(int(TRADE_START_LEVEL or 3), 7))

            # Default behavior: long must be >= start_level and short must be 0
            if not (buy_count >= start_level and sell_count == 0):
                self._log_signal(base_symbol, "SKIP",
                    f"Need L>={start_level} S=0",
                    long_level=buy_count, short_level=sell_count)
                start_index += 1
                continue





            response = self.place_buy_order(
                str(uuid.uuid4()),
                "buy",
                "market",
                full_symbol,
                allocation_in_usd,
            )

            if response and "errors" not in response:
                trades_made = True
                # Do NOT pre-trigger any DCA levels. Hardcoded DCA will mark levels only when it hits your loss thresholds.
                self.dca_levels_triggered[base_symbol] = []

                # Fresh trade -> clear any rolling 24h DCA window for this coin
                self._reset_dca_window_for_trade(base_symbol, sold=False)

                # Reset trailing PM state for this coin (fresh trade, fresh trailing logic)
                self.trailing_pm.pop(base_symbol, None)

                self._log_signal(base_symbol, "ENTRY",
                    f"L{buy_count} S{sell_count} -> ${allocation_in_usd:.2f}",
                    long_level=buy_count, short_level=sell_count)
                _log(
                    f"Starting new trade for {full_symbol} (AI start signal long={buy_count}, short={sell_count}). "
                    f"Allocating ${allocation_in_usd:.2f}."
                )
                time.sleep(5)
                holdings = self.get_holdings()
                holding_full_symbols = [f"{h['asset_code']}-USD" for h in holdings.get("results", [])]


            start_index += 1

        # If any trades were made, recalculate the cost basis
        if trades_made:
            time.sleep(5)
            _log("Trades were made in this iteration. Recalculating cost basis...")
            new_cost_basis = self.calculate_cost_basis()
            if new_cost_basis:
                self.cost_basis = new_cost_basis
                _log("Cost basis recalculated successfully.")
            else:
                _log("Failed to recalculate cost basis.")
            self.initialize_dca_levels()

        # --- GUI HUB STATUS WRITE ---
        try:
            status = {
                "timestamp": time.time(),
                "account": {
                    "total_account_value": total_account_value,
                    "buying_power": buying_power,
                    "holdings_sell_value": holdings_sell_value,
                    "holdings_buy_value": holdings_buy_value,
                    "percent_in_trade": in_use,
                    # trailing PM config (matches what's printed above current trades)
                    "pm_start_pct_no_dca": float(getattr(self, "pm_start_pct_no_dca", 0.0)),
                    "pm_start_pct_with_dca": float(getattr(self, "pm_start_pct_with_dca", 0.0)),
                    "trailing_gap_pct": float(getattr(self, "trailing_gap_pct", 0.0)),
                },
                "positions": positions,
            }
            self._append_jsonl(
                ACCOUNT_VALUE_HISTORY_PATH,
                {"ts": status["timestamp"], "total_account_value": total_account_value},
            )
            self._write_trader_status(status)
        except Exception as e:
            _log(f"[ERROR] status write: {e}")




    def run(self):
        loop_count = 0
        while True:
            try:
                loop_count += 1
                if loop_count == 1 or loop_count % 120 == 0:
                    _log(f"[LOOP] manage_trades iteration #{loop_count}")
                self.manage_trades()
                time.sleep(0.5)
            except Exception as e:
                _log(f"[ERROR] Exception in manage_trades loop: {e}")
                _log(traceback.format_exc())
                time.sleep(5)

if __name__ == "__main__":
    trading_bot = CryptoAPITrading()
    trading_bot.run()
