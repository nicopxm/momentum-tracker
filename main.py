import time
import logging
import threading
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta, timezone

CDMX = timezone(timedelta(hours=-6))
from dotenv import load_dotenv
import os
import requests
import pandas as pd
from supabase import create_client, Client
from ingestion import fetch_all_active_products, fetch_product_details, store_price

# --- Setup ---
load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

supabase: Client = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

PRODUCTS      = []
_products_lock = threading.Lock()   # guards PRODUCTS across scheduler threads

# ─────────────────────────────────────────────
# CONFIGS
# ─────────────────────────────────────────────

MOMENTUM_CONFIGS = {
    "5min":  {"lookback": 5,  "price_change_pct": 2.5, "volume_ratio": 3.0},
    "15min": {"lookback": 15, "price_change_pct": 3.0, "volume_ratio": 2.0},
    "30min": {"lookback": 30, "price_change_pct": 5.0, "volume_ratio": 1.8},
    "1hour": {"lookback": 60, "price_change_pct": 7.0, "volume_ratio": 1.5},
}

ACCELERATION_CONFIGS = {
    "30min": {"lookback_minutes": 30,  "min_gain": 3.0,  "min_24hr": 8.0},
    "1hour": {"lookback_minutes": 60,  "min_gain": 5.0,  "min_24hr": 8.0},
    "3hour": {"lookback_minutes": 180, "min_gain": 8.0,  "min_24hr": 5.0},
    "8hour": {"lookback_minutes": 480, "min_gain": 10.0, "min_24hr": 3.0},
}

# Alert thresholds
GAINER_24HR_THRESHOLD    = 15.0
LOSER_24HR_THRESHOLD     = -20.0
PUMP_ALERT_THRESHOLD     = 3.0
DUMP_ALERT_THRESHOLD     = 20.0
LOW_VOLUME_THRESHOLD     = 0.5
INTRADAY_RANGE_THRESHOLD = 10.0
MEGA_PUMP_THRESHOLDS     = [30, 50, 75, 100]
MIN_VOLUME_24H           = 50_000

# ── Dynamic L2 thresholds (Option #2) ────────────────────────────────────────
DYNAMIC_L2_MIN_24HR       = 15.0   # only activate dynamic threshold above this 24hr %
DYNAMIC_L2_FRESH_LEG_PCT  = 1.0    # min % gain in last 30 min (safeguard 1)
DYNAMIC_L2_PEAK_PROXIMITY = 8.0    # must be >8% below peak_price (safeguard 2)
DYNAMIC_L2_MIN_ACCEL      = 1      # minimum accel stages required (safeguard 3)
DYNAMIC_L2_MIN_THRESHOLD  = 1.3    # floor: volume ratio never lowered below this
EARLY_L2_MAX_PER_CYCLE    = 3      # max dynamic L2 alerts fired per scan cycle

# ── TP/SL Position Management ─────────────────────────────────────────────────
TP0_PCT              = 15.0   # early partial profit threshold %
TP0_SELL_PCT         = 25.0   # sell 25% at TP0; remainder holds for TP1/trail
TP1_PCT              = 20.0   # partial profit threshold %
TP1_SELL_STANDARD    = 50     # % to sell at TP1 for standard L2
TP1_SELL_EXPLOSIVE   = 30     # % to sell at TP1 for explosive L2 (accel >= 3)
EXPLOSIVE_ACCEL_MIN  = 3      # accel stages required for explosive profile
BREAKEVEN_TRIGGER    = 12.0   # % gain that moves hard stop to entry price
HARD_STOP_STANDARD   = -8.0   # hard stop for standard/explosive profiles
HARD_STOP_GRINDER    = -12.0  # wider stop for slow grinders (they breathe more)
TRAILING_STOP_PCT    = 12.0   # trail -12% from highest confirmed close post-TP1
GRINDER_TRAIL_PCT    = 15.0   # grinders trail wider at -15%
WEAK_SIGNAL_HOURS    = 2.0    # hours before time stop check
L2_STREAK_THRESHOLD  = 2      # min consecutive L2 cycles before alerting
L2_STREAK_WINDOW_HRS = 6      # hours within which L2s count as consecutive
WEAK_SIGNAL_GAIN_MIN = 3.0    # min % gain required to avoid time stop

GRINDER_TIERS = [
    {
        "label":       "🐢🐢🐢 FAST GRINDER",
        "min_days":    1.0,
        "min_rate":    10.0,
        "max_avg_vol": 1.0,
        "cooldown":    "grinder_fast",
        "action":      "Compounding fast — watch for vol spike = explosion"
    },
    {
        "label":       "🐢🐢 MID GRINDER",
        "min_days":    2.0,
        "min_rate":    4.0,
        "max_avg_vol": 0.8,
        "cooldown":    "grinder_mid",
        "action":      "Multi-day momentum — add on dips"
    },
    {
        "label":       "🐢 SLOW GRINDER",
        "min_days":    4.0,
        "min_rate":    2.0,
        "max_avg_vol": 0.6,
        "cooldown":    "grinder_slow",
        "action":      "Quietly compounding — watch for breakout"
    },
]

# ─────────────────────────────────────────────
# CLASSIFICATION
# ─────────────────────────────────────────────

def classify_coin(state: dict) -> str:
    accel          = state.get("accel_count", 0) or 0
    l2             = state.get("l2_fired", False)
    ch24           = float(state.get("change_24hr", 0) or 0)
    dump           = state.get("dump_fired", False)
    range_from_low = float(state.get("range_from_low", 0) or 0)

    if dump and ch24 > 15:
        return "🔻 PULLBACK"
    if dump:
        return "⚫ COOLING"

    peak    = float(state.get("peak_price", 0) or 0)
    current = float(state.get("current_price", 0) or 0)
    if peak > 0 and current > 0:
        drop_from_peak = (peak - current) / peak * 100
        if drop_from_peak > 20 and ch24 > 10:
            return "🔻 PULLBACK"
        if drop_from_peak > 20 and ch24 <= 10:
            return "⚫ COOLING"

    l2_type = str(state.get("l2_type", "") or "")
    if l2 and l2_type == "volume" and accel >= 2 and ch24 >= 5:
        return "🔴 HIGH CONVICTION"
    if l2 and l2_type == "volume" and accel >= 1 and ch24 >= 5:
        return "🟠 BUILDING"
    if l2 and l2_type == "accel" and ch24 >= 5:
        return "🟠 BUILDING"

    # INTRADAY MOVER before WATCHING — catches big moves from low
    if range_from_low >= INTRADAY_RANGE_THRESHOLD and not dump:
        return "👀 INTRADAY MOVER"

    if ch24 >= 15:
        return "🟡 WATCHING"

    if state.get("slow_grinder") and not dump:
        return "🐢 SLOW GRINDER"
    if state.get("coiling") and not l2:
        return "🔄 COILING"
    if l2 and ch24 < 5:
        return "⚫ COOLING"
    return "⚪ NEUTRAL"


def calc_probability(state: dict) -> int:
    score          = 0
    ch24           = float(state.get("change_24hr", 0) or 0)
    range_from_low = float(state.get("range_from_low", 0) or 0)

    if state.get("l2_fired"):
        score += 30
        if str(state.get("l2_type", "") or "") == "accel":
            score -= 20
    if state.get("accel_count", 0) >= 1: score += 15
    if state.get("accel_count", 0) >= 2: score += 15
    if state.get("accel_count", 0) >= 3: score += 15
    if state.get("accel_count", 0) >= 4: score += 10
    if ch24 >= 15:                        score += 10
    if ch24 >= 25:                        score += 5
    if range_from_low >= 20:              score += 10
    elif range_from_low >= 15:            score += 5
    peak    = float(state.get("peak_price", 0) or 0)
    current = float(state.get("current_price", 0) or 0)
    if peak > 0 and current > 0:
        drop_from_peak = (peak - current) / peak * 100
        if drop_from_peak > 20: score -= 20
        if drop_from_peak > 35: score -= 20
    return max(min(score, 95), 0)


# ─────────────────────────────────────────────
# MARKET CONTEXT GLOBALS
# ─────────────────────────────────────────────

BTC_CHANGE_24HR  = 0.0   # updated each scan cycle when BTC-USD is processed
FEAR_GREED_VALUE = 50    # updated by daily cron via fetch_fear_greed()
FEAR_GREED_LABEL = "Neutral"


# ─────────────────────────────────────────────
# TECHNICAL INDICATORS
# ─────────────────────────────────────────────

def calculate_rsi(df: pd.DataFrame, period: int = 14) -> float:
    """
    RSI-14 using Wilder's smoothing. Needs period+1 candles minimum.
    Returns 50.0 (neutral) when insufficient data.
    Interpretation: <45 fresh, 45-60 building, 60-75 extended, >75 overbought.
    """
    if len(df) < period + 1:
        return 50.0
    try:
        closes = df["close"].astype(float)
        delta  = closes.diff()
        gains  = delta.clip(lower=0)
        losses = (-delta).clip(lower=0)

        # Wilder's initial avg
        avg_gain = gains.iloc[1:period + 1].mean()
        avg_loss = losses.iloc[1:period + 1].mean()
        if pd.isna(avg_gain) or pd.isna(avg_loss):
            return 50.0

        # Wilder's smoothing for remaining candles
        for i in range(period + 1, len(delta)):
            avg_gain = (avg_gain * (period - 1) + gains.iloc[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses.iloc[i]) / period

        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        result = round(100 - (100 / (1 + rs)), 2)
        if pd.isna(result):
            return 50.0
        return result
    except Exception:
        return 50.0


def calculate_macd(df: pd.DataFrame,
                   fast: int = 12, slow: int = 26, signal_period: int = 9) -> dict:
    """
    MACD (12/26/9). Bullish cross = MACD crossed above signal in last 3 candles.
    Returns neutral defaults when insufficient data (need slow + signal_period candles).
    """
    default = {"macd_line": 0.0, "macd_signal": 0.0,
               "macd_histogram": 0.0, "macd_bullish": False}
    if len(df) < slow + signal_period:
        return default
    try:
        closes      = df["close"].astype(float)
        ema_fast    = closes.ewm(span=fast,   adjust=False).mean()
        ema_slow    = closes.ewm(span=slow,   adjust=False).mean()
        macd_line   = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal_period, adjust=False).mean()
        histogram   = macd_line - signal_line

        # Bullish cross: detected if it happened in any of the last 3 candles
        recent_cross = any(
            macd_line.iloc[-i] > signal_line.iloc[-i] and
            macd_line.iloc[-(i + 1)] <= signal_line.iloc[-(i + 1)]
            for i in range(1, 4)
            if len(df) >= i + 2
        )
        return {
            "macd_line":      round(float(macd_line.iloc[-1]), 8),
            "macd_signal":    round(float(signal_line.iloc[-1]), 8),
            "macd_histogram": round(float(histogram.iloc[-1]), 8),
            "macd_bullish":   recent_cross,
        }
    except Exception:
        return default


def calculate_emas(df: pd.DataFrame) -> dict:
    """
    EMA-20 and EMA-50 from close prices.
    price_above_ema20 + ema20_above_ema50 = full bullish structure.
    Returns neutral defaults when fewer than 50 candles available.
    """
    default = {"ema_20": 0.0, "ema_50": 0.0,
               "price_above_ema20": False, "ema20_above_ema50": False}
    if len(df) < 50:
        return default
    try:
        closes        = df["close"].astype(float)
        current_price = float(closes.iloc[-1])
        ema_20        = float(closes.ewm(span=20, adjust=False).mean().iloc[-1])
        ema_50        = float(closes.ewm(span=50, adjust=False).mean().iloc[-1])
        return {
            "ema_20":            round(ema_20, 8),
            "ema_50":            round(ema_50, 8),
            "price_above_ema20": current_price > ema_20,
            "ema20_above_ema50": ema_20 > ema_50,
        }
    except Exception:
        return default


def calculate_indicators(df: pd.DataFrame) -> dict:
    """
    Calculate all TA indicators from candle data.
    Zero new API calls — pure math on existing 350-candle fetch.
    Called once per coin per cycle; results passed into all downstream functions.
    """
    base = {
        "rsi": 50.0, "macd_line": 0.0, "macd_signal": 0.0,
        "macd_histogram": 0.0, "macd_bullish": False,
        "ema_20": 0.0, "ema_50": 0.0,
        "price_above_ema20": False, "ema20_above_ema50": False,
    }
    if df.empty or len(df) < 30:
        return base
    base["rsi"] = calculate_rsi(df)
    base.update(calculate_macd(df))
    base.update(calculate_emas(df))
    return base


# ── Indicator label helpers (used in alert formatting) ───────────────────────

def rsi_label(rsi: float) -> str:
    if rsi < 45:  return f"RSI {rsi:.0f} 🟢"
    if rsi < 60:  return f"RSI {rsi:.0f} 🟡"
    if rsi < 75:  return f"RSI {rsi:.0f} 🟠 extended"
    return             f"RSI {rsi:.0f} 🔴 overbought"

def macd_label(bullish: bool, histogram: float) -> str:
    if bullish:       return "MACD ✅ bullish cross"
    if histogram > 0: return "MACD 🟡 positive"
    return                   "MACD ⚪ neutral"

def ema_label(above_20: bool, ema20_above_50: bool) -> str:
    if above_20 and ema20_above_50: return "EMA ✅ bull structure"
    if above_20:                    return "EMA 🟡 above EMA20"
    return                                 "EMA ⚪ below EMA20"

def rs_btc_label(rs: float) -> str:
    if rs > 10: return f"RS/BTC +{rs:.1f}% 🔥"
    if rs > 3:  return f"RS/BTC +{rs:.1f}% 🟢"
    if rs > 0:  return f"RS/BTC +{rs:.1f}% 🟡"
    return             f"RS/BTC {rs:.1f}% ⚪"

def fg_label(value: int, label: str) -> str:
    if value <= 25: return f"F&G {value} 😨 {label}"
    if value <= 45: return f"F&G {value} 😟 {label}"
    if value <= 55: return f"F&G {value} 😐 {label}"
    if value <= 75: return f"F&G {value} 😏 {label}"
    return                 f"F&G {value} 🤑 {label}"


# ─────────────────────────────────────────────
# UNIFIED MOMENTUM SCORE (0-100)
# ─────────────────────────────────────────────

def calculate_momentum_score(signal: dict, accel_count: int = 0,
                              multi_leg_state: str | None = None) -> int:
    """
    Unified 0-100 confidence score combining all signal layers.
    Based on 29 days of live trade outcomes.

    Thresholds:
    ≥75 — HIGH CONVICTION 🔥 act now
    50-74 — MODERATE ✅ take the trade
    30-49 — LOW ⚠️ wait for confirmation
    <30 — SKIP ❌ too weak
    """
    score = 0

    # ── Core signal ───────────────────────────────────────────────────────────
    l2_type = signal.get("l2_type", "")
    if l2_type == "volume":
        score += 30   # volume-confirmed L2 — strongest base signal
    elif l2_type == "accel":
        score += 15   # accel L2 — weaker, waiting for volume

    # ── Acceleration stages ───────────────────────────────────────────────────
    score += min(accel_count * 10, 30)  # max +30 for 3+ stages

    # ── RSI ───────────────────────────────────────────────────────────────────
    rsi = float(signal.get("rsi") or 50)
    if rsi < 45:
        score += 15   # fresh momentum — best entries historically
    elif rsi < 60:
        score += 10   # building — good entries
    elif rsi < 75:
        score += 0    # extended — no bonus
    else:
        score -= 10   # overbought — FIS-USD at RSI 83 faded -13%

    # ── MACD ─────────────────────────────────────────────────────────────────
    if signal.get("macd_bullish"):
        score += 10

    # ── EMA structure ─────────────────────────────────────────────────────────
    if signal.get("price_above_ema20") and signal.get("ema20_above_ema50"):
        score += 10   # full bullish structure

    # ── Relative strength vs BTC ──────────────────────────────────────────────
    rs = float(signal.get("rs_vs_btc") or 0)
    if rs > 10:
        score += 10   # strong coin-specific demand
    elif rs > 3:
        score += 5    # outperforming market

    # ── HH/HL multi-leg structure ─────────────────────────────────────────────
    if multi_leg_state == "CONFIRMED":
        score += 5
    elif multi_leg_state == "PRE_BREAKOUT":
        score += 3

    # ── Fear & Greed context ──────────────────────────────────────────────────
    if FEAR_GREED_VALUE <= 25:
        score += 5    # extreme fear = historically best buying conditions

    return max(0, min(score, 100))


def score_label(score: int) -> str:
    if score >= 75: return f"Score {score}/100 🔥 HIGH CONVICTION"
    if score >= 50: return f"Score {score}/100 ✅ MODERATE"
    if score >= 30: return f"Score {score}/100 ⚠️ LOW"
    return                 f"Score {score}/100 ❌ WEAK"


def fetch_fear_greed():
    """Fetch Crypto Fear & Greed Index from Alternative.me. Free, no key needed.
    Called once per day by midnight cron. Updates global FEAR_GREED_VALUE/LABEL."""
    global FEAR_GREED_VALUE, FEAR_GREED_LABEL
    try:
        resp = requests.get("https://api.alternative.me/fng/", timeout=5)
        data = resp.json()["data"][0]
        FEAR_GREED_VALUE = int(data["value"])
        FEAR_GREED_LABEL = data["value_classification"]
        # Persist to DB so it survives restarts
        supabase.table("market_context").upsert({
            "id":         1,
            "fear_greed": FEAR_GREED_VALUE,
            "fg_label":   FEAR_GREED_LABEL,
            "updated_at": datetime.utcnow().isoformat(),
        }).execute()
        log.info(f"Fear & Greed: {FEAR_GREED_VALUE} ({FEAR_GREED_LABEL})")
    except Exception as e:
        log.error(f"fetch_fear_greed failed: {e}")

def get_dynamic_volume_threshold(base_threshold: float, change_24hr: float) -> float:
    """Scales volume threshold down on strong runners. Floor enforced at DYNAMIC_L2_MIN_THRESHOLD."""
    if change_24hr >= 20.0:
        return max(base_threshold * 0.60, DYNAMIC_L2_MIN_THRESHOLD)
    if change_24hr >= 15.0:
        return max(base_threshold * 0.75, DYNAMIC_L2_MIN_THRESHOLD)
    return base_threshold


def is_volume_trending_up(volume_series: list) -> bool:
    """Safeguard 4: at least 2 of last 3 candles show rising volume.
    Returns False when series < 4 elements — dynamic L2 blocked when history is short."""
    if len(volume_series) < 4:
        return False
    rising = sum(1 for i in range(1, len(volume_series)) if volume_series[i] > volume_series[i-1])
    return rising >= 2


def evaluate_dynamic_l2(signal_data: dict, current_price: float,
                         peak_price: float, base_vol_threshold: float) -> tuple:
    """
    Evaluates all safeguards for Dynamic L2 eligibility.
    Returns: (is_dynamic, threshold, l2_type)
    """
    change_24hr  = float(signal_data.get("change_24hr", 0))
    accel_count  = int(signal_data.get("accel_count", 0))
    price_30min  = float(signal_data.get("price_change_30min", 0))
    vol_trend_up = bool(signal_data.get("volume_trend_up", False))
    coiling      = bool(signal_data.get("coiling", False))

    # Base gate — strong runner OR coiling
    if change_24hr < DYNAMIC_L2_MIN_24HR and not coiling:
        return False, base_vol_threshold, "standard"

    # Safeguard 1 — Fresh Leg: price actively rising in last 30 min
    if price_30min < DYNAMIC_L2_FRESH_LEG_PCT:
        return False, base_vol_threshold, "standard"

    # Safeguard 2 — Peak Proximity: must be >8% below recent peak
    if peak_price > 0:
        dist_from_peak = (peak_price - current_price) / peak_price * 100
        if dist_from_peak < DYNAMIC_L2_PEAK_PROXIMITY:
            return False, base_vol_threshold, "standard"

    # Safeguard 3 — Acceleration: at least 1 confirmed accel stage
    if accel_count < DYNAMIC_L2_MIN_ACCEL:
        return False, base_vol_threshold, "standard"

    # Safeguard 4 — Volume Trend: 2 of last 3 candles rising
    if not vol_trend_up:
        return False, base_vol_threshold, "standard"

    # All safeguards passed — calculate lowered threshold
    dynamic_threshold = get_dynamic_volume_threshold(base_vol_threshold, change_24hr)
    if dynamic_threshold < base_vol_threshold:
        return True, dynamic_threshold, "dynamic"

    return False, base_vol_threshold, "standard"


# ─────────────────────────────────────────────
# TELEGRAM
# ─────────────────────────────────────────────

def send_telegram_alert(message: str):
    if not TOKEN or not CHAT_ID:
        log.warning("Telegram credentials missing")
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": message},
            timeout=5
        )
    except Exception as e:
        log.error(f"Telegram send failed: {e}")


def should_alert(product_id: str, timeframe: str) -> bool:
    cooldown = (14400 if timeframe == "24hour"
                else 43200 if timeframe == "coiling"
                else 14400 if timeframe == "grinder_fast"
                else 28800 if timeframe == "grinder_mid"
                else 43200 if timeframe == "grinder_slow"
                else 28800 if timeframe == "hh_hl"
                else 7200  if timeframe == "pump"
                else 3600  if timeframe == "early_l2"
                else 43200 if timeframe == "new_listing"  # 12hr — prevents repeat fires
                else 14400 if timeframe == "intraday"     # 4hr — was 1hr, too noisy
                else 3600  if ("accel" in timeframe
                               or timeframe in ("volspike", "txspike")
                               or timeframe.startswith("mega_"))
                else 1800)
    try:
        res = supabase.table("alert_cooldowns")\
            .select("alerted_at")\
            .eq("product_id", product_id)\
            .eq("timeframe", timeframe)\
            .execute()
        if res.data:
            last = datetime.fromisoformat(res.data[0]["alerted_at"])
            if (datetime.now(last.tzinfo) - last).total_seconds() < cooldown:
                return False
        supabase.table("alert_cooldowns").upsert({
            "product_id": product_id,
            "timeframe":  timeframe,
            "alerted_at": datetime.utcnow().isoformat()
        }, on_conflict="product_id,timeframe").execute()
        return True
    except Exception as e:
        log.error(f"Cooldown check failed: {e}")
        return True


# ─────────────────────────────────────────────
# CANDLES
# ─────────────────────────────────────────────

def fetch_candles(product_id: str, limit: int = 65) -> pd.DataFrame:
    url = f"https://api.coinbase.com/api/v3/brokerage/market/products/{product_id}/candles"
    try:
        resp = requests.get(
            url,
            params={"granularity": "ONE_MINUTE", "limit": limit},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=5
        )
        if resp.status_code == 200:
            candles = resp.json().get("candles", [])
            if not candles:
                return pd.DataFrame()
            df = pd.DataFrame(candles)
            if "start" not in df.columns and "timestamp" not in df.columns:
                return pd.DataFrame()
            df = df.rename(columns={"start": "timestamp"})
            df["timestamp"] = pd.to_datetime(df["timestamp"].astype(int), unit="s")
            df = df.sort_values("timestamp").reset_index(drop=True)
            df[["open","high","low","close","volume"]] = \
                df[["open","high","low","close","volume"]].astype(float)
            return df
    except Exception as e:
        log.error(f"Candle fetch failed for {product_id}: {e}")
    return pd.DataFrame()


# ─────────────────────────────────────────────
# SIGNAL DETECTION
# ─────────────────────────────────────────────

def check_momentum(df: pd.DataFrame, config: dict, label: str, change_24hr: float,
                   low_liquidity: bool = False,
                   accel_count: int = 0, peak_price: float = 0.0,
                   price_change_30min: float = 0.0, vol_trend_up: bool = False,
                   coiling: bool = False,
                   rs_vs_btc: float = 0.0) -> dict | None:
    if len(df) < config["lookback"] + 1:
        return None

    current_price  = float(df["close"].iloc[-1])
    lookback_price = float(df["close"].iloc[-(config["lookback"] + 1)])
    price_change   = round(((current_price - lookback_price) / lookback_price) * 100, 2)

    if abs(price_change) < config["price_change_pct"]:
        return None

    avg_volume     = df["volume"].iloc[-11:-1].mean()
    current_volume = df["volume"].iloc[-1]
    volume_ratio   = round(current_volume / avg_volume, 2) if avg_volume > 0 else 0

    # ── Dynamic L2 evaluation ─────────────────────────────────────────────────
    # price_change_30min and vol_trend_up are pre-computed once per coin in the
    # main loop and passed in — avoids repeating the same DataFrame slice 4×
    is_dynamic, dynamic_threshold, _ = evaluate_dynamic_l2(
        signal_data={
            "change_24hr":        change_24hr,
            "accel_count":        accel_count,
            "price_change_30min": price_change_30min,
            "volume_trend_up":    vol_trend_up,
            "coiling":            coiling,   # real value from state_cache — coiling bypass now live
        },
        current_price      = current_price,
        peak_price         = peak_price,
        base_vol_threshold = config["volume_ratio"],
    )

    if is_dynamic:
        log.info(
            f"⚡ Dynamic L2 eligible [{label}]: threshold {config['volume_ratio']:.1f}x "
            f"→ {dynamic_threshold:.1f}x | 24hr: {change_24hr:+.1f}% | "
            f"30min: +{price_change_30min:.1f}% | accel: {accel_count}"
        )

    # ── L2 classification ─────────────────────────────────────────────────────
    effective_threshold = dynamic_threshold if is_dynamic else config["volume_ratio"]

    # ── RS vs BTC market-beta filter ─────────────────────────────────────────
    # If BTC is pumping hard (>3%) and this coin has low relative strength (<5%
    # outperformance), it's market beta not coin-specific momentum. Suppress L2.
    # This blocks June 7-style mass events where 40+ coins fired simultaneously.
    is_market_beta = (BTC_CHANGE_24HR >= 3.0 and rs_vs_btc < 5.0)

    if (volume_ratio >= effective_threshold
            and price_change > 0
            and change_24hr > 0
            and not low_liquidity
            and not is_market_beta):
        level   = 2
        l2_type = "dynamic" if is_dynamic else "volume"
    else:
        level   = 1
        l2_type = ""

    # Skip low volume dumps — noise
    if price_change < 0 and volume_ratio < 1.5:
        return None

    return {
        "timeframe":    label,
        "price_change": price_change,
        "price":        current_price,
        "direction":    "🚀 PUMP" if price_change > 0 else "🔻 DUMP",
        "volume_ratio": volume_ratio,
        "level":        level,
        "l2_type":      l2_type,
        "is_dynamic":   is_dynamic,
    }


def get_avg_volume_ratio(product_id: str, minutes: int = 30) -> float:
    try:
        cutoff = (datetime.utcnow() - timedelta(minutes=minutes)).isoformat()
        res = supabase.table("signals")\
            .select("volume_ratio")\
            .eq("product_id", product_id)\
            .gte("triggered_at", cutoff)\
            .execute()
        if res.data:
            ratios = [float(r["volume_ratio"]) for r in res.data if r["volume_ratio"]]
            return round(sum(ratios) / len(ratios), 2) if ratios else 0.0
    except:
        pass
    return 0.0


def fetch_momentum_cache() -> dict:
    """Fetch all recent momentum_history into memory once per cycle."""
    try:
        cutoff = (datetime.utcnow() - timedelta(hours=9)).isoformat()
        res = supabase.table("momentum_history")\
            .select("product_id, price, change_24hr, recorded_at")\
            .gte("recorded_at", cutoff)\
            .order("recorded_at", desc=False)\
            .execute()

        cache = {}
        if res.data:
            for row in res.data:
                pid = row["product_id"]
                if pid not in cache:
                    cache[pid] = []
                cache[pid].append(row)

        log.info(f"Momentum cache loaded — {len(res.data)} rows for {len(cache)} coins")
        return cache
    except Exception as e:
        log.error(f"fetch_momentum_cache failed: {e}")
        return {}


def fetch_state_cache() -> dict:
    """
    Fetch all fields needed by update_coin_state + check_tp_sl for all coins
    in ONE query. Eliminates 231 individual SELECT * per cycle.
    """
    try:
        res = supabase.table("coin_state")\
            .select("product_id, accel_count, accel_stages, coiling, "
                    "l2_streak, l2_fired, l2_price, l2_fired_at, l2_type, "
                    "dump_fired, dump_price, dump_fired_at, "
                    "peak_price, peak_at, slow_grinder, "
                    "tp0_hit, tp0_price, tp0_fired_at, "
                    "tp1_hit, tp2_hit, sl_hit, time_stop_hit, "
                    "position_closed, trailing_high")\
            .execute()
        return {r["product_id"]: r for r in (res.data or [])}
    except Exception as e:
        log.error(f"fetch_state_cache failed: {e}")
        return {}


# ─────────────────────────────────────────────
# DAILY SNAPSHOTS
# ─────────────────────────────────────────────

def write_daily_snapshot(product_id: str, price: float, change_24hr: float,
                         volume_24h: float, high_price: float = 0.0,
                         low_price: float = 0.0):
    """
    Upsert today's snapshot for a coin.
    Preserves open_price (first write of day) and maintains the absolute
    daily high/low across multiple mid-day updates from run_slow_grinder_scan.

    Without this fix: every 6hr update would overwrite high/low with current
    price, flattening daily candles to High == Low == Close and breaking
    the HH/HL pattern detector.
    """
    try:
        today = datetime.utcnow().date().isoformat()

        # Fetch existing row to preserve open, high, low
        existing = supabase.table("daily_snapshots")\
            .select("open_price, high_price, low_price")\
            .eq("product_id", product_id)\
            .eq("date", today)\
            .execute()

        open_price = price
        final_high = high_price or price
        final_low  = low_price  or price

        if existing.data:
            row = existing.data[0]
            # Preserve first price of the day as open
            if row.get("open_price"):
                open_price = float(row["open_price"])
            # Keep the highest high seen today
            if row.get("high_price"):
                final_high = max(float(row["high_price"]), final_high)
            # Keep the lowest low seen today
            if row.get("low_price"):
                final_low = min(float(row["low_price"]), final_low)

        supabase.table("daily_snapshots").upsert({
            "product_id":  product_id,
            "date":        today,
            "open_price":  open_price,
            "close_price": price,
            "high_price":  final_high,
            "low_price":   final_low,
            "change_24hr": change_24hr,
            "volume_24h":  volume_24h,
        }).execute()
    except Exception as e:
        log.error(f"write_daily_snapshot failed for {product_id}: {e}")


def fetch_daily_snapshots(product_id: str, days: int = 7) -> list:
    """Fetch last N days of snapshots for one coin. Tiny payload — max 7 rows."""
    try:
        cutoff = (datetime.utcnow().date() - timedelta(days=days)).isoformat()
        res = supabase.table("daily_snapshots")\
            .select("date, open_price, close_price, high_price, low_price, change_24hr")\
            .eq("product_id", product_id)\
            .gte("date", cutoff)\
            .order("date", desc=False)\
            .execute()
        return res.data or []
    except Exception as e:
        log.error(f"fetch_daily_snapshots failed for {product_id}: {e}")
        return []


def fetch_all_daily_snapshots(days: int = 7) -> dict:
    """
    Batch fetch all coins' daily snapshots in ONE query.
    Used by grinder scan to avoid 231 individual queries.
    Returns dict keyed by product_id.
    """
    try:
        cutoff = (datetime.utcnow().date() - timedelta(days=days)).isoformat()
        res = supabase.table("daily_snapshots")\
            .select("product_id, date, open_price, close_price, high_price, low_price, change_24hr")\
            .gte("date", cutoff)\
            .order("date", desc=False)\
            .execute()
        cache = {}
        for row in (res.data or []):
            cache.setdefault(row["product_id"], []).append(row)
        log.info(f"Daily snapshots loaded — {len(res.data or [])} rows for {len(cache)} coins")
        return cache
    except Exception as e:
        log.error(f"fetch_all_daily_snapshots failed: {e}")
        return {}


# ─────────────────────────────────────────────
# HH/HL PATTERN DETECTION
# ─────────────────────────────────────────────

def check_hh_hl_pattern(daily_data: list) -> dict | None:
    """
    Detect Higher Highs / Higher Lows multi-leg uptrend from daily snapshots.

    State 1 — CONFIRMED: both HH and HL present. Strong uptrend.
               Entry: buy pullbacks toward last_hl_price.
    State 2 — PRE_BREAKOUT: HL only, no new high yet. Best entry —
               price compressed between rising support and resistance.

    3% tolerance on lows: crypto wicks pierce without breaking trend.
    Requires 66%+ of daily transitions showing higher lows (core requirement).
    Requires 50%+ showing higher highs for CONFIRMED state.
    """
    if len(daily_data) < 3:
        return None

    data  = sorted(daily_data, key=lambda x: x["date"])
    lows  = [float(d["low_price"])  for d in data if d.get("low_price")]
    highs = [float(d["high_price"]) for d in data if d.get("high_price")]

    if len(lows) < 3 or len(highs) < 3:
        return None

    n        = len(data) - 1
    hl_count = sum(1 for i in range(1, len(lows))  if lows[i]  >= lows[i-1]  * 0.97)
    hh_count = sum(1 for i in range(1, len(highs)) if highs[i] > highs[i-1])
    hl_pct   = hl_count / n
    hh_pct   = hh_count / n

    # Higher lows are the core requirement — without this it's not a trend
    if hl_pct < 0.66:
        return None

    state = "CONFIRMED" if hh_pct >= 0.50 else "PRE_BREAKOUT"

    start_price        = float(data[0].get("open_price") or data[0].get("close_price") or 0)
    current_price      = float(data[-1].get("close_price") or 0)
    last_low           = lows[-1]

    if start_price <= 0 or current_price <= 0:
        return None

    total_gain_pct     = round((current_price - start_price) / start_price * 100, 2)
    pct_above_last_hl  = round((current_price - last_low) / last_low * 100, 2) if last_low > 0 else 0

    return {
        "state":             state,
        "days":              len(data),
        "hl_count":          hl_count,
        "hh_count":          hh_count,
        "total_gain_pct":    total_gain_pct,
        "last_hl_price":     last_low,
        "pct_above_last_hl": pct_above_last_hl,
    }


def check_acceleration(product_id: str, current_24hr: float,
                       current_price: float, cache: dict) -> list:
    signals      = []
    product_cache = cache.get(product_id, [])
    if not product_cache:
        return signals

    for label, config in ACCELERATION_CONFIGS.items():
        try:
            if current_24hr < config["min_24hr"]:
                continue

            cutoff     = (datetime.utcnow() - timedelta(minutes=config["lookback_minutes"] + 3))
            limit_time = (datetime.utcnow() - timedelta(minutes=config["lookback_minutes"] - 3))

            matching = [
                r for r in product_cache
                if cutoff <= datetime.fromisoformat(
                    r["recorded_at"].replace("Z", "+00:00")).replace(tzinfo=None) <= limit_time
            ]

            if not matching:
                continue

            past_row     = matching[0]
            past_24hr    = float(past_row["change_24hr"])
            past_price   = float(past_row["price"])
            acceleration = round(current_24hr - past_24hr, 2)

            if acceleration >= config["min_gain"]:
                signals.append({
                    "label":         label,
                    "acceleration":  acceleration,
                    "past_24hr":     past_24hr,
                    "current_24hr":  current_24hr,
                    "past_price":    past_price,
                    "current_price": current_price,
                })
                log.info(f"🔥 ACCEL [{label}] {product_id}: {past_24hr:+.2f}% → {current_24hr:+.2f}%")

        except Exception as e:
            log.error(f"Acceleration check failed for {product_id} [{label}]: {e}")
    return signals


COILING_SKIP_LIST = {
    "BTC-USD", "ETH-USD", "SOL-USD", "BNB-USD", "XRP-USD",
    "ADA-USD", "DOGE-USD", "AVAX-USD", "DOT-USD", "LTC-USD",
    "BCH-USD", "SHIB-USD", "LINK-USD", "UNI-USD", "ATOM-USD",
    "ETC-USD", "XLM-USD", "ALGO-USD", "ICP-USD", "FIL-USD",
    "AAVE-USD", "GRT-USD", "SAND-USD", "MANA-USD", "SNX-USD",
    "CRV-USD", "SUSHI-USD", "COMP-USD", "YFI-USD", "MKR-USD",
    "SUI-USD", "APT-USD", "ARB-USD", "OP-USD", "TRUMP-USD",
    "BONK-USD", "WIF-USD", "PEPE-USD", "FLOKI-USD", "TAO-USD",
    "RENDER-USD", "FET-USD", "NEAR-USD", "SEI-USD",
    "HBAR-USD", "BLUR-USD", "POL-USD", "LINEA-USD", "ZK-USD",
    "CAKE-USD", "SWFTC-USD", "INX-USD",
}

def _reset_coiling(product_id: str):
    supabase.table("coin_state").update({"coiling": False})\
        .eq("product_id", product_id).execute()

def check_coiling(product_id: str, price: float, change_24hr: float,
                  volume_24h: float = 0, history: list | None = None):
    try:
        if product_id in COILING_SKIP_LIST:
            _reset_coiling(product_id)
            return
        if change_24hr < -5:
            _reset_coiling(product_id)
            return
        if change_24hr > 15:
            _reset_coiling(product_id)
            return
        if volume_24h < 1_000_000:
            _reset_coiling(product_id)
            return

        # Use pre-fetched history if provided (batch mode) — else query individually
        if history is not None:
            rows = history
        else:
            cutoff = (datetime.utcnow() - timedelta(hours=24)).isoformat()
            res = supabase.table("momentum_history")\
                .select("price, recorded_at")\
                .eq("product_id", product_id)\
                .gte("recorded_at", cutoff)\
                .order("recorded_at", desc=False)\
                .execute()
            rows = res.data or []

        if not rows or len(rows) < 50:
            _reset_coiling(product_id)
            return

        prices  = [float(r["price"]) for r in rows]
        times   = [r["recorded_at"] for r in rows]
        first_t = datetime.fromisoformat(times[0].replace("Z", "+00:00"))
        last_t  = datetime.fromisoformat(times[-1].replace("Z", "+00:00"))
        hours   = (last_t - first_t).total_seconds() / 3600

        if hours < 6:
            _reset_coiling(product_id)
            return

        lo             = min(prices)
        hi             = max(prices)
        coil_range_pct = round(((hi - lo) / lo * 100) if lo > 0 else 0, 2)

        if coil_range_pct < 2 or coil_range_pct >= 8:
            _reset_coiling(product_id)
            return

        supabase.table("coin_state").update({
            "coiling":        True,
            "coil_start_at":  times[0],
            "coil_range_pct": coil_range_pct,
        }).eq("product_id", product_id).execute()

        # Coiling alerts silenced — 0 proven outcomes in 29 days
        # Flag stays in DB and dashboard; alert only if L2 fires on a coiling coin
        log.info(f"🔄 COILING detected: {product_id} range {coil_range_pct:.1f}% over {hours:.0f}hrs")

    except Exception as e:
        log.error(f"check_coiling failed for {product_id}: {e}")


def check_slow_grinder(product_id: str, price: float, change_24hr: float,
                       daily_snapshots: list,
                       hh_hl_pending: list | None = None):
    """
    Detect slow grinders and HH/HL multi-leg patterns from daily_snapshots.
    Reads from daily_snapshots (5 rows max) instead of momentum_history
    (1440 rows) — 99% egress reduction.

    Also detects HH/HL structure and writes multi_leg_state to coin_state.
    """
    try:
        # ── Reset if coin already pumped hard — no longer a grinder ──────────
        if change_24hr > 20:
            supabase.table("coin_state").update({
                "slow_grinder":   False,
                "multi_leg_state": None,
            }).eq("product_id", product_id).execute()
            return

        if change_24hr < 2 and not daily_snapshots:
            return

        # ── HH/HL pattern — runs regardless of grinder qualification ─────────
        hh_hl = check_hh_hl_pattern(daily_snapshots)
        if hh_hl:
            supabase.table("coin_state").update({
                "multi_leg_state":   hh_hl["state"],
                "last_hl_price":     hh_hl["last_hl_price"],
                "pct_above_last_hl": hh_hl["pct_above_last_hl"],
            }).eq("product_id", product_id).execute()

            if should_alert(product_id, "hh_hl") and hh_hl_pending is not None:
                # Quality filters — skip stablecoins, low volume, hard dumping coins
                is_stable = product_id in {
                    "USDT-USD", "USDC-USD", "USD1-USD", "USDS-USD",
                    "PAXG-USD", "CBETH-USD"
                }
                # Fetch avg_volume_6hr from coin_state for quality filter
                try:
                    cs = supabase.table("coin_state")\
                        .select("avg_volume_6hr")\
                        .eq("product_id", product_id).execute()
                    avg_vol = float((cs.data[0].get("avg_volume_6hr") or 0) if cs.data else 0)
                except Exception:
                    avg_vol = 0
                has_volume  = avg_vol >= 50_000
                not_dumping = -10.0 <= change_24hr <= 50.0

                if not is_stable and has_volume and not_dumping:
                    state_label = "✅ CONFIRMED UPTREND" if hh_hl["state"] == "CONFIRMED" \
                                  else "⚡ PRE-BREAKOUT (best entry)"
                    entry_quality = "🟢 At support — good entry" if hh_hl["pct_above_last_hl"] < 10 \
                                    else "🟡 Building — wait for dip" if hh_hl["pct_above_last_hl"] < 20 \
                                    else "🔴 Extended — wait for pullback to support"
                    # Quality score for sorting — CONFIRMED > PRE_BREAKOUT, higher total gain = better
                    quality = (10 if hh_hl["state"] == "CONFIRMED" else 5) + hh_hl.get("total_gain_pct", 0)
                    hh_hl_pending.append((quality, product_id,
                        f"🔺 MULTI-LEG TREND {product_id}\n"
                        f"Structure  : {state_label}\n"
                        f"Pattern    : {hh_hl['hh_count']} higher highs, {hh_hl['hl_count']} higher lows "
                        f"over {hh_hl['days']} days\n"
                        f"Total move : +{hh_hl['total_gain_pct']:.1f}%\n"
                        f"Support    : ${hh_hl['last_hl_price']:.6f} (last higher low)\n"
                        f"Now        : ${price:.6f} (+{hh_hl['pct_above_last_hl']:.1f}% above support)\n"
                        f"Entry      : {entry_quality}\n"
                        f"24hr       : {change_24hr:+.1f}%"
                    ))
                    log.info(f"🔺 HH/HL queued: {product_id} {hh_hl['state']} "
                             f"+{hh_hl['total_gain_pct']:.1f}% over {hh_hl['days']}d")
        else:
            # Clear stale HH/HL state if pattern no longer holds
            supabase.table("coin_state").update({
                "multi_leg_state": None,
            }).eq("product_id", product_id).execute()

        # ── Slow grinder detection from daily snapshots ───────────────────────
        if change_24hr < 2:
            supabase.table("coin_state").update({"slow_grinder": False})\
                .eq("product_id", product_id).execute()
            return

        if not daily_snapshots or len(daily_snapshots) < 2:
            supabase.table("coin_state").update({"slow_grinder": False})\
                .eq("product_id", product_id).execute()
            return

        data        = sorted(daily_snapshots, key=lambda x: x["date"])
        start_price = float(data[0].get("open_price") or data[0].get("close_price") or 0)
        days        = len(data)

        if start_price <= 0 or days < 1:
            return

        total_ratio = price / start_price
        daily_rate  = round((pow(total_ratio, 1.0 / days) - 1) * 100, 2)
        total_gain  = round((total_ratio - 1) * 100, 2)

        if daily_rate <= 0 or total_gain <= 0:
            supabase.table("coin_state").update({"slow_grinder": False})\
                .eq("product_id", product_id).execute()
            return

        # Approach B — last 25% avg must be 5%+ above first 25% avg
        prices    = [float(d.get("close_price") or 0) for d in data]
        quarter   = max(len(prices) // 4, 1)
        avg_first = sum(prices[:quarter]) / quarter
        avg_last  = sum(prices[-quarter:]) / quarter

        if avg_last <= avg_first * 1.05:
            supabase.table("coin_state").update({"slow_grinder": False})\
                .eq("product_id", product_id).execute()
            return

        # ── Capped mean avg_vol — spike-resistant ─────────────────────────────
        # One 73x candle used to destroy the avg (EDGEX bug).
        # Cap each ratio at 10x before averaging — outlier becomes noise.
        sig_cutoff = (datetime.utcnow() - timedelta(hours=24)).isoformat()
        sig_res = supabase.table("signals")\
            .select("volume_ratio")\
            .eq("product_id", product_id)\
            .gte("triggered_at", sig_cutoff)\
            .execute()

        if not sig_res.data:
            avg_vol = 0.0
        else:
            ratios  = [float(r["volume_ratio"]) for r in sig_res.data if r.get("volume_ratio")]
            capped  = [min(r, 10.0) for r in ratios]   # cap outliers — 73x → 10x
            avg_vol = round(sum(capped) / len(capped), 2) if capped else 0.0

        matched_tier = None
        for tier in GRINDER_TIERS:
            if (days       >= tier["min_days"] and
                daily_rate >= tier["min_rate"] and
                avg_vol    <= tier["max_avg_vol"]):
                matched_tier = tier
                break

        if not matched_tier:
            supabase.table("coin_state").update({"slow_grinder": False})\
                .eq("product_id", product_id).execute()
            return

        supabase.table("coin_state").update({"slow_grinder": True})\
            .eq("product_id", product_id).execute()

        if should_alert(product_id, matched_tier["cooldown"]):
            send_telegram_alert(
                f"{matched_tier['label']} {product_id}\n"
                f"Daily rate   : +{daily_rate:.1f}%/day compounded\n"
                f"Days active  : {days:.1f} days\n"
                f"Total gain   : +{total_gain:.1f}% from start\n"
                f"Avg volume   : {avg_vol:.2f}x (pure grind)\n"
                f"24hr change  : {change_24hr:+.1f}%\n"
                f"Price        : ${price:.6f}\n"
                f"Action       : {matched_tier['action']}"
            )
            log.info(f"{matched_tier['label']} alert: {product_id} "
                     f"+{daily_rate:.1f}%/day over {days:.1f}d")

    except Exception as e:
        log.error(f"check_slow_grinder failed for {product_id}: {e}")


def check_volume_spike(product_id: str, df: pd.DataFrame, change_24hr: float, price: float):
    try:
        if len(df) < 16:
            return
        current_15min_vol = df["volume"].iloc[-15:].sum()
        avg_per_candle    = df["volume"].mean()
        avg_15min_vol     = avg_per_candle * 15
        if avg_15min_vol <= 0:
            return
        volume_ratio = current_15min_vol / avg_15min_vol
        if volume_ratio >= 10:
            p_now        = float(df["close"].iloc[-1])
            p_15         = float(df["close"].iloc[-16])
            price_change = round((p_now - p_15) / p_15 * 100, 2) if p_15 > 0 else 0
            if should_alert(product_id, "volspike"):
                send_telegram_alert(
                    f"⚡ VOLUME SPIKE {product_id}\n"
                    f"Volume     : {volume_ratio:.1f}x 6hr average\n"
                    f"Price Δ    : {price_change:+.2f}%\n"
                    f"24hr       : {change_24hr:+.1f}%\n"
                    f"Price      : ${price:.6f}\n"
                    f"Action     : Unusual volume — watch for breakout"
                )
    except Exception as e:
        log.error(f"check_volume_spike failed for {product_id}: {e}")


def check_tx_spike(product_id: str, df: pd.DataFrame, change_24hr: float, price: float):
    try:
        if "transactions" not in df.columns or len(df) < 31:
            return
        current_tx = float(df["transactions"].iloc[-1])
        avg_tx     = df["transactions"].iloc[-31:-1].mean()
        if avg_tx <= 0:
            return
        if current_tx / avg_tx >= 10:
            avg_vol      = df["volume"].iloc[-31:-1].mean()
            cur_vol      = df["volume"].iloc[-1]
            vol_ratio    = cur_vol / avg_vol if avg_vol > 0 else 0
            p_now        = float(df["close"].iloc[-1])
            p_15         = float(df["close"].iloc[-16]) if len(df) >= 16 else p_now
            price_change = round((p_now - p_15) / p_15 * 100, 2) if p_15 > 0 else 0
            if should_alert(product_id, "txspike"):
                send_telegram_alert(
                    f"📊 TRANSACTION SPIKE {product_id}\n"
                    f"Transactions: {int(current_tx)} vs avg {avg_tx:.0f}\n"
                    f"Volume      : {vol_ratio:.1f}x avg\n"
                    f"Price Δ     : {price_change:+.2f}%\n"
                    f"24hr        : {change_24hr:+.1f}%\n"
                    f"Action      : Unusual activity — possible breakout incoming"
                )
    except Exception as e:
        log.error(f"check_tx_spike failed for {product_id}: {e}")


# ─────────────────────────────────────────────
# TP/SL POSITION MANAGEMENT
# ─────────────────────────────────────────────

def _hof_time_stop(product_id: str, state: dict, price: float):
    """Insert a time/dump exit into Hall of Fame. Shared by 2hr and 6hr exit paths."""
    try:
        l2p  = float(state.get("l2_price") or 0)
        peak = float(state.get("peak_price") or 0)
        gain = round((price - l2p) / l2p * 100, 1) if l2p > 0 else 0
        if l2p > 0 and gain >= 5.0:
            tp2_hit   = bool(state.get("tp2_hit") or False)
            tp1_hit   = bool(state.get("tp1_hit") or False)
            tp0_hit   = bool(state.get("tp0_hit") or False)
            exit_type = (
                "TP1_TRAIL"   if tp2_hit  else
                "TP0_PARTIAL" if tp0_hit  else
                "TIME_STOP"
            )
            supabase.table("hall_of_fame").insert({
                "product_id":  product_id,
                "l2_type":     str(state.get("l2_type") or "volume"),
                "l2_fired_at": str(state.get("l2_fired_at") or ""),
                "l2_price":    l2p,
                "peak_price":  peak,
                "peak_gain":   round((peak - l2p) / l2p * 100, 1) if l2p > 0 else 0,
                "tp0_hit":     tp0_hit,
                "tp1_hit":     tp1_hit,
                "tp2_hit":     tp2_hit,
                "accel_count": int(state.get("accel_count") or 0),
                "rsi":         state.get("rsi"),
                "rs_vs_btc":   state.get("rs_vs_btc"),
                "exit_type":   exit_type,
                "exit_gain":   gain,
            }).execute()
            log.info(f"🏆 Hall of Fame: {product_id} {exit_type} +{gain}%")
    except Exception as e:
        log.warning(f"Hall of Fame insert failed ({product_id}): {e}")


def check_tp_sl(product_id: str, price: float, state: dict,
                df: pd.DataFrame | None = None):
    """
    Monitors open L2 positions for TP/SL targets every scan cycle.
    Boolean flags prevent re-firing — no cooldown table needed.
    Trailing stop uses highest confirmed CLOSE (wick-filtered, not candle high).

    Flow:
    1. Weak signal exit (2hr, gain < 3%)
    2. Hard stop / Breakeven stop
    3. TP1 partial profit at +20% → activate trailing stop
    4. Trailing stop on remainder post-TP1
    """
    # Only track standard L2 positions — dynamic L2 is UNCONFIRMED
    if not state.get("l2_fired"):
        return
    if state.get("position_closed"):
        return
    # Skip accel-only L2s — higher risk, no TP/SL tracking
    if str(state.get("l2_type") or "") == "accel":
        return

    l2_price = float(state.get("l2_price") or 0)
    if l2_price <= 0:
        return

    gain_pct    = round((price - l2_price) / l2_price * 100, 2)
    l2_fired_at = state.get("l2_fired_at")
    is_grinder  = bool(state.get("slow_grinder", False))
    accel_count = int(state.get("accel_count") or 0)
    l2_type     = str(state.get("l2_type") or "")
    peak_price  = float(state.get("peak_price") or price)
    now         = datetime.utcnow().isoformat()

    # ── Wick-filtered trailing high from confirmed closes ─────────────────────
    if df is not None and not df.empty and len(df) >= 15:
        recent_close_high = float(df["close"].iloc[-15:].max())
    else:
        recent_close_high = price

    existing_trail = float(state.get("trailing_high") or 0)
    effective_trail_high = max(existing_trail, recent_close_high, price)

    def _update(fields: dict):
        fields["updated_at"] = now
        try:
            supabase.table("coin_state").update(fields)\
                .eq("product_id", product_id).execute()
        except Exception as e:
            log.error(f"TP/SL state update failed for {product_id}: {e}")

    # ── Weak signal exit: 2hr, no traction ───────────────────────────────────
    # Slow grinders are exempt — they move over days, not hours
    # Exit only if position is negative — flat/slightly positive coins may be slow starters
    if l2_fired_at and not state.get("tp1_hit") and not state.get("time_stop_hit") and not is_grinder:
        try:
            l2_time = datetime.fromisoformat(
                l2_fired_at.replace("Z", "+00:00")).replace(tzinfo=None)
            hours_elapsed = (datetime.utcnow() - l2_time).total_seconds() / 3600
            if hours_elapsed >= WEAK_SIGNAL_HOURS and gain_pct < 0.0:
                _update({"time_stop_hit": True, "position_closed": True})
                send_telegram_alert(
                    format_weak_signal_alert(product_id, l2_price, price,
                                             gain_pct, hours_elapsed))
                log.info(f"WEAK SIGNAL EXIT: {product_id} {gain_pct:+.1f}% after {hours_elapsed:.1f}hr")
                _hof_time_stop(product_id, state, price)
                return

            if hours_elapsed >= 6.0 and gain_pct < 3.0 and not is_grinder and not state.get("tp1_hit"):
                _update({"time_stop_hit": True, "position_closed": True})
                send_telegram_alert(
                    format_weak_signal_alert(product_id, l2_price, price,
                                             gain_pct, hours_elapsed))
                log.info(f"WEAK SIGNAL EXIT (6hr): {product_id} {gain_pct:+.1f}% after {hours_elapsed:.1f}hr — no traction")
                _hof_time_stop(product_id, state, price)
                return
        except Exception as e:
            log.error(f"Time stop check failed for {product_id}: {e}")

    # ── Dynamic hard stop / breakeven stop ────────────────────────────────────
    # BE triggered if peak ever reached +12% (derived from peak_price, no new field)
    peak_gain    = (peak_price - l2_price) / l2_price * 100 if l2_price > 0 else 0
    be_triggered = peak_gain >= BREAKEVEN_TRIGGER
    hard_stop    = HARD_STOP_GRINDER if is_grinder else HARD_STOP_STANDARD

    # ── TP0 — early partial profit lock ──────────────────────────────────────
    if not state.get("tp0_hit") and not state.get("tp1_hit") and l2_price > 0:
        intra_high = recent_close_high if df is not None else price
        gain_now = ((intra_high - l2_price) / l2_price) * 100
        if gain_now >= TP0_PCT:
            try:
                supabase.table("coin_state").update({
                    "tp0_hit":      True,
                    "tp0_price":    intra_high,
                    "tp0_fired_at": now,
                }).eq("product_id", product_id).execute()
                send_telegram_alert(
                    f"🟡 TP0 PARTIAL — {product_id}\n"
                    f"Entry (L2) : ${l2_price:.6f}\n"
                    f"Now         : ${intra_high:.6f} (+{gain_now:.1f}%)\n"
                    f"Action      : Sell {TP0_SELL_PCT:.0f}% now — early profit lock\n"
                    f"Remainder   : Holding for TP1 at +{TP1_PCT:.0f}%"
                )
                log.info(f"TP0 fired: {product_id} +{gain_now:.1f}%")
            except Exception as e:
                log.warning(f"TP0 update failed ({product_id}): {e}")

    # ── Intra-cycle TP1 check ─────────────────────────────────────────────────
    # If the intra-cycle close high crossed +20% but poll price hasn't caught it,
    # fire TP1 now before the hard stop can trigger. Prevents fast spikes from
    # being missed entirely when they retrace within one 7-minute window.
    intra_gain = (effective_trail_high - l2_price) / l2_price * 100 if l2_price > 0 else 0
    if intra_gain >= TP1_PCT and not state.get("tp1_hit"):
        _update({
            "tp1_hit":       True,
            "trailing_high": effective_trail_high,
        })
        send_telegram_alert(
            format_tp1_alert(product_id, l2_price, effective_trail_high,
                             intra_gain, l2_type, accel_count))
        log.info(f"💰 TP1 HIT (intra-cycle): {product_id} {intra_gain:+.1f}% — "
                 f"poll price {gain_pct:+.1f}%")
        # Don't return — continue to check if hard stop also fires on poll price
        # At this point tp1_hit=True so BE floor is now active

    # ── Peak-based hard stop for proven winners ───────────────────────────────
    # If coin has shown real strength (peak >= 20%), measure stop from peak
    # not from entry. Prevents stopping out a +100% winner on a normal retrace.
    if peak_gain >= 20.0 and not state.get("tp1_hit"):
        # Coin proved itself but TP1 wasn't caught — use peak-based stop
        drop_from_peak = (peak_price - price) / peak_price * 100 if peak_price > 0 else 0
        peak_stop_threshold = 15.0  # -15% from peak triggers stop
        if drop_from_peak >= peak_stop_threshold and not state.get("sl_hit"):
            _update({"sl_hit": True, "position_closed": True})
            send_telegram_alert(
                format_hard_stop_alert(product_id, l2_price, price, gain_pct, be_triggered))
            log.info(f"🛑 PEAK-BASED STOP: {product_id} {gain_pct:+.1f}% "
                     f"(-{drop_from_peak:.1f}% from peak ${peak_price:.6f})")
            return
    else:
        # Standard hard stop — coin never proved itself
        effective_stop = 0.0 if be_triggered else hard_stop
        if gain_pct <= effective_stop and not state.get("sl_hit") and not state.get("tp1_hit"):
            _update({"sl_hit": True, "position_closed": True})
            send_telegram_alert(
                format_hard_stop_alert(product_id, l2_price, price, gain_pct, be_triggered))
            log.info(f"{'🛡️ BE STOP' if be_triggered else '🛑 HARD STOP'}: "
                     f"{product_id} {gain_pct:+.1f}%")
            return

    # ── Post-TP1: trailing stop on remainder ──────────────────────────────────
    if state.get("tp1_hit") and not state.get("tp2_hit") and not state.get("sl_hit"):
        # Update trailing_high with latest wick-filtered close
        if effective_trail_high > existing_trail:
            _update({"trailing_high": effective_trail_high})

        trail_pct  = GRINDER_TRAIL_PCT if is_grinder else TRAILING_STOP_PCT
        trail_floor = effective_trail_high * (1 - trail_pct / 100)

        if price <= trail_floor and effective_trail_high > 0:
            _update({"tp2_hit": True, "position_closed": True})
            send_telegram_alert(
                format_trailing_stop_alert(product_id, l2_price, price,
                                           effective_trail_high, gain_pct, is_grinder))
            log.info(f"🔄 TRAILING STOP: {product_id} {gain_pct:+.1f}% "
                     f"(-{trail_pct:.0f}% from ${effective_trail_high:.6f})")
            # ── Hall of Fame insert — TP1 + trail exit ───────────────────────────
            try:
                l2p   = float(state.get("l2_price") or 0)
                peak  = float(state.get("peak_price") or 0)
                trail = float(state.get("trailing_high") or 0)
                if l2p > 0 and trail > 0:
                    supabase.table("hall_of_fame").insert({
                        "product_id":       product_id,
                        "l2_type":          str(state.get("l2_type") or "volume"),
                        "l2_fired_at":      str(state.get("l2_fired_at") or ""),
                        "l2_price":         l2p,
                        "peak_price":       peak,
                        "peak_gain":        round((peak - l2p) / l2p * 100, 1) if l2p > 0 else 0,
                        "trailing_high":    trail,
                        "trail_exit_gain":  round((trail - l2p) / l2p * 100, 1) if l2p > 0 else 0,
                        "tp1_hit":          True,
                        "tp2_hit":          True,
                        "accel_count":      int(state.get("accel_count") or 0),
                        "rsi":              state.get("rsi"),
                        "rs_vs_btc":        state.get("rs_vs_btc"),
                        "exit_type":        "TP1_TRAIL",
                        "exit_gain":        round((trail - l2p) / l2p * 100, 1) if l2p > 0 else 0,
                    }).execute()
                    log.info(f"Hall of Fame: {product_id} TP1_TRAIL +{round((trail - l2p) / l2p * 100, 1)}%")
            except Exception as e:
                log.warning(f"Hall of Fame insert failed ({product_id}): {e}")
        return

    # ── TP1 — partial profit at +20% ─────────────────────────────────────────
    if gain_pct >= TP1_PCT and not state.get("tp1_hit"):
        _update({
            "tp1_hit":       True,
            "trailing_high": effective_trail_high,  # seed trailing high at TP1
        })
        send_telegram_alert(
            format_tp1_alert(product_id, l2_price, price, gain_pct, l2_type, accel_count))
        log.info(f"💰 TP1 HIT: {product_id} {gain_pct:+.1f}% — "
                 f"{'explosive' if accel_count >= EXPLOSIVE_ACCEL_MIN else 'standard'} profile")

def update_coin_state(product_id: str, price: float, change_24hr: float,
                      signal: dict | None, accel_signals: list,
                      range_from_low: float = 0.0, full_range: float = 0.0,
                      high_24h: float = 0.0, low_24h: float = 0.0,
                      low_liquidity: bool = False, avg_volume_6hr: float = 0.0,
                      intra_cycle_high: float = 0.0,
                      indicators: dict | None = None,
                      rs_vs_btc: float = 0.0,
                      existing: dict | None = None):
    """
    Update or insert coin state. Accepts pre-fetched state dict from state_cache
    to avoid per-coin SELECT * (saves ~65MB/day egress on 231 coins × 288 cycles).
    """
    try:
        now = datetime.utcnow().isoformat()

        if existing:
            accel_stages = list(existing.get("accel_stages") or [])
            accel_count  = int(existing.get("accel_count") or 0)
            for a in accel_signals:
                if a["label"] not in accel_stages:
                    accel_stages.append(a["label"])
                    accel_count += 1

            l2_fired      = existing.get("l2_fired", False)
            l2_price      = existing.get("l2_price")
            l2_fired_at   = existing.get("l2_fired_at")
            l2_type       = existing.get("l2_type", "")
            dump_fired    = existing.get("dump_fired", False)
            dump_price    = existing.get("dump_price")
            dump_fired_at = existing.get("dump_fired_at")

            # ── Freeze peak_price once position is closed ─────────────────────
            # If position_closed or time_stop_hit, stop updating peak_price.
            # Without this, peak_price keeps climbing weeks after exit giving
            # false impression that the original position caught the full move.
            position_is_closed = (
                existing.get("position_closed")
                or existing.get("time_stop_hit")
                or existing.get("sl_hit")
            )
            if position_is_closed:
                peak_price = float(existing.get("peak_price") or 0)
                peak_at    = existing.get("peak_at")
            else:
                peak_price = max(float(existing.get("peak_price") or 0), price, intra_cycle_high)
                peak_at    = existing.get("peak_at")
                # Update peak timestamp if either poll price or intra-cycle high is new high
                if max(price, intra_cycle_high) > float(existing.get("peak_price") or 0):
                    peak_at = now

            dump_price_val = float(existing.get("dump_price") or 0)
            if dump_fired and dump_price_val > 0 and price >= dump_price_val * 1.033:
                dump_fired = False
                log.info(f"dump_fired reset: {product_id} recovered above dump price")

            if signal:
                vol_l2   = (signal["level"] == 2
                            and signal["price_change"] > 0
                            and change_24hr > 0
                            and signal.get("l2_type") != "dynamic")
                accel_l2 = (signal["price_change"] > 0 and accel_count >= 2
                            and change_24hr >= 6 and not low_liquidity)
                is_l2    = vol_l2 or accel_l2
                position_was_closed = bool(
                    existing.get("position_closed") or
                    existing.get("time_stop_hit") or
                    existing.get("sl_hit")
                )
                if is_l2 and (not l2_fired or position_was_closed):
                    l2_fired          = True
                    l2_price          = price
                    l2_fired_at       = now
                    signal["level"]   = 2
                    l2_type           = signal.get("l2_type", "volume") if vol_l2 else "accel"
                    signal["l2_type"] = l2_type
                    # Reset TP/SL flags — fresh position, clean slate
                    log.info(f"New L2 on {product_id} — resetting TP/SL flags")

                if signal["price_change"] < 0 and not dump_fired:
                    dump_fired    = True
                    dump_price    = price
                    dump_fired_at = now

                if signal["price_change"] > 0 and dump_fired:
                    dump_fired = False

            # ── Determine if TP/SL flags should reset (new L2 fired) ─────────
            # Two cases require a full reset:
            # 1. l2_fired just flipped False → True (fresh coin)
            # 2. l2_fired on a previously closed position (re-entry after exit)
            # Without case 2, peak_price and peak_at from the old position
            # bleed into the new one, corrupting P&L data.
            was_closed   = bool(existing.get("position_closed") or
                                existing.get("time_stop_hit") or
                                existing.get("sl_hit"))
            new_l2_fired = (l2_fired and not existing.get("l2_fired")) or \
                           (l2_fired and was_closed and
                            l2_fired_at != existing.get("l2_fired_at"))

            # Reset peak to current price on re-entry so peak_gain
            # reflects only the new position, not the old one
            if new_l2_fired:
                peak_price = price
                peak_at    = now

            # Update L2 streak counter
            if is_l2:
                existing_streak = int((existing or {}).get("l2_streak") or 0)
                last_l2_at = (existing or {}).get("l2_fired_at")
                if last_l2_at:
                    try:
                        last_dt = datetime.fromisoformat(
                            str(last_l2_at).replace("Z", "+00:00")
                        ).replace(tzinfo=None)
                        hours_since = (datetime.utcnow() - last_dt).total_seconds() / 3600
                        l2_streak = existing_streak + 1 if hours_since <= L2_STREAK_WINDOW_HRS else 1
                    except Exception:
                        l2_streak = 1
                else:
                    l2_streak = 1
            else:
                l2_streak = 0

            state = {
                "accel_count":     accel_count,
                "accel_stages":    accel_stages,
                "l2_fired":        l2_fired,
                "l2_price":        l2_price,
                "l2_fired_at":     l2_fired_at,
                "l2_type":         l2_type,
                "dump_fired":      dump_fired,
                "dump_price":      dump_price,
                "dump_fired_at":   dump_fired_at,
                "peak_price":      peak_price,
                "peak_at":         peak_at,
                "change_24hr":     change_24hr,
                "current_price":   price,
                "range_from_low":  range_from_low,
                "full_range":      full_range,
                "high_24h":        high_24h,
                "low_24h":         low_24h,
                "avg_volume_6hr":  avg_volume_6hr,
                # Reset TP/SL on new L2 — fresh position
                **({"tp1_hit": False, "tp2_hit": False, "sl_hit": False,
                    "time_stop_hit": False, "position_closed": False,
                    "trailing_high": None} if new_l2_fired else {}),
                "updated_at":      now,
            }
            if indicators:
                state["rsi"]               = indicators.get("rsi")
                state["macd_line"]         = indicators.get("macd_line")
                state["macd_signal"]       = indicators.get("macd_signal")
                state["macd_histogram"]    = indicators.get("macd_histogram")
                state["macd_bullish"]      = indicators.get("macd_bullish", False)
                state["ema_20"]            = indicators.get("ema_20")
                state["ema_50"]            = indicators.get("ema_50")
                state["price_above_ema20"] = indicators.get("price_above_ema20", False)
                state["ema20_above_ema50"] = indicators.get("ema20_above_ema50", False)
            state["rs_vs_btc"]      = rs_vs_btc if rs_vs_btc is not None and not pd.isna(float(rs_vs_btc)) else 0.0
            if is_l2:
                existing_streak = int((existing or {}).get("l2_streak") or 0)
                last_l2_at = (existing or {}).get("l2_fired_at")
                if last_l2_at:
                    try:
                        last_dt = datetime.fromisoformat(
                            str(last_l2_at).replace("Z", "+00:00")
                        ).replace(tzinfo=None)
                        hours_since = (datetime.utcnow() - last_dt).total_seconds() / 3600
                        l2_streak = existing_streak + 1 if hours_since <= L2_STREAK_WINDOW_HRS else 1
                    except Exception:
                        l2_streak = 1
                else:
                    l2_streak = 1
            else:
                l2_streak = 0
            state["l2_streak"]      = l2_streak
            state["classification"] = classify_coin({**existing, **state})
            supabase.table("coin_state").update(state)\
                .eq("product_id", product_id).execute()

        else:
            # New coin — insert fresh row
            l2_fired = bool(signal and signal["level"] == 2
                            and signal["price_change"] > 0 and change_24hr > 0)
            l2_type  = signal.get("l2_type", "") if l2_fired and signal else ""
            cls = "🟡 WATCHING" if change_24hr >= 15 else \
                  "👀 INTRADAY MOVER" if range_from_low >= INTRADAY_RANGE_THRESHOLD else \
                  "⚪ NEUTRAL"
            state = {
                "product_id":         product_id,
                "first_signal_at":    now,
                "first_signal_price": price,
                "l2_fired":           l2_fired,
                "l2_price":           price if l2_fired else None,
                "l2_fired_at":        now if l2_fired else None,
                "l2_type":            l2_type,
                "accel_count":        len(accel_signals),
                "accel_stages":       [a["label"] for a in accel_signals],
                "peak_price":         price,
                "peak_at":            now,
                "dump_fired":         False,
                "change_24hr":        change_24hr,
                "current_price":      price,
                "range_from_low":     range_from_low,
                "full_range":         full_range,
                "high_24h":           high_24h,
                "low_24h":            low_24h,
                "avg_volume_6hr":     avg_volume_6hr,
                "classification":     cls,
                "status":             "WATCHING",
                "updated_at":         now,
            }
            if indicators:
                state["rsi"]               = indicators.get("rsi")
                state["macd_line"]         = indicators.get("macd_line")
                state["macd_signal"]       = indicators.get("macd_signal")
                state["macd_histogram"]    = indicators.get("macd_histogram")
                state["macd_bullish"]      = indicators.get("macd_bullish", False)
                state["ema_20"]            = indicators.get("ema_20")
                state["ema_50"]            = indicators.get("ema_50")
                state["price_above_ema20"] = indicators.get("price_above_ema20", False)
                state["ema20_above_ema50"] = indicators.get("ema20_above_ema50", False)
            state["rs_vs_btc"] = rs_vs_btc if rs_vs_btc is not None and not pd.isna(float(rs_vs_btc)) else 0.0
            supabase.table("coin_state").insert(state).execute()

    except Exception as e:
        log.error(f"update_coin_state failed for {product_id}: {e}")

        if existing:
            accel_stages = existing.get("accel_stages") or []
            accel_count  = existing.get("accel_count", 0)
            for a in accel_signals:
                if a["label"] not in accel_stages:
                    accel_stages.append(a["label"])
                    accel_count += 1

            l2_fired      = existing.get("l2_fired", False)
            l2_price      = existing.get("l2_price")
            l2_fired_at   = existing.get("l2_fired_at")
            l2_type       = existing.get("l2_type", "")
            dump_fired    = existing.get("dump_fired", False)
            dump_price    = existing.get("dump_price")
            dump_fired_at = existing.get("dump_fired_at")
            peak_price    = max(existing.get("peak_price") or 0, price)
            peak_at       = existing.get("peak_at")

            # Always update peak if current price is higher — runs every cycle
            if price > (existing.get("peak_price") or 0):
                peak_price = price
                peak_at    = now

            # Reset dump_fired if price recovered 3.3%+ above dump price
            dump_price_val = float(existing.get("dump_price") or 0)
            if dump_fired and dump_price_val > 0 and price >= dump_price_val * 1.033:
                dump_fired = False
                log.info(f"dump_fired reset: {product_id} recovered above dump price")

            if signal:
                # Dynamic L2 is a separate track — does NOT set l2_fired
                vol_l2   = (signal["level"] == 2
                            and signal["price_change"] > 0
                            and change_24hr > 0
                            and signal.get("l2_type") != "dynamic")
                accel_l2 = (signal["price_change"] > 0 and accel_count >= 2
                            and change_24hr >= 6 and not low_liquidity)
                is_l2    = vol_l2 or accel_l2
                position_was_closed = bool(
                    existing.get("position_closed") or
                    existing.get("time_stop_hit") or
                    existing.get("sl_hit")
                )
                if is_l2 and (not l2_fired or position_was_closed):
                    l2_fired          = True
                    l2_price          = price
                    l2_fired_at       = now
                    signal["level"]   = 2
                    l2_type           = signal.get("l2_type", "volume") if vol_l2 else "accel"
                    signal["l2_type"] = l2_type

                if signal["price_change"] < 0 and not dump_fired:
                    dump_fired    = True
                    dump_price    = price
                    dump_fired_at = now

                if signal["price_change"] > 0 and dump_fired:
                    dump_fired = False

            state = {
                "accel_count":       accel_count,
                "accel_stages":      accel_stages,
                "l2_fired":          l2_fired,
                "l2_price":          l2_price,
                "l2_fired_at":       l2_fired_at,
                "l2_type":           l2_type,
                "dump_fired":        dump_fired,
                "dump_price":        dump_price,
                "dump_fired_at":     dump_fired_at,
                "peak_price":        peak_price,
                "peak_at":           peak_at,
                "change_24hr":       change_24hr,
                "current_price":     price,
                "range_from_low":    range_from_low,
                "full_range":        full_range,
                "high_24h":          high_24h,
                "low_24h":           low_24h,
                "avg_volume_6hr":    avg_volume_6hr,
                "updated_at":        now,
            }
            state["rsi"]               = indicators.get("rsi") if indicators else None
            state["macd_line"]         = indicators.get("macd_line") if indicators else None
            state["macd_signal"]       = indicators.get("macd_signal") if indicators else None
            state["macd_histogram"]    = indicators.get("macd_histogram") if indicators else None
            state["macd_bullish"]      = indicators.get("macd_bullish", False) if indicators else False
            state["ema_20"]            = indicators.get("ema_20") if indicators else None
            state["ema_50"]            = indicators.get("ema_50") if indicators else None
            state["price_above_ema20"] = indicators.get("price_above_ema20", False) if indicators else False
            state["ema20_above_ema50"] = indicators.get("ema20_above_ema50", False) if indicators else False
            state["rs_vs_btc"] = rs_vs_btc if rs_vs_btc is not None and not pd.isna(float(rs_vs_btc)) else 0.0
            state["classification"] = classify_coin({**existing, **state})
            supabase.table("coin_state").update(state)\
                .eq("product_id", product_id).execute()

        else:
            l2_fired = bool(signal and signal["level"] == 2 and signal["price_change"] > 0 and change_24hr > 0)
            l2_type  = signal.get("l2_type", "") if l2_fired and signal else ""
            cls = "🟡 WATCHING" if change_24hr >= 15 else \
                  "👀 INTRADAY MOVER" if range_from_low >= INTRADAY_RANGE_THRESHOLD else \
                  "⚪ NEUTRAL"
            state = {
                "product_id":         product_id,
                "first_signal_at":    now,
                "first_signal_price": price,
                "l2_fired":           l2_fired,
                "l2_price":           price if l2_fired else None,
                "l2_fired_at":        now if l2_fired else None,
                "l2_type":            l2_type,
                "accel_count":        len(accel_signals),
                "accel_stages":       [a["label"] for a in accel_signals],
                "peak_price":         price,
                "peak_at":            now,
                "dump_fired":         False,
                "change_24hr":        change_24hr,
                "current_price":      price,
                "range_from_low":     range_from_low,
                "full_range":         full_range,
                "high_24h":           high_24h,
                "low_24h":            low_24h,
                "avg_volume_6hr":     avg_volume_6hr,
                "classification":    cls,
                "status":            "WATCHING",
                "updated_at":        now,
            }
            state["rsi"]               = indicators.get("rsi") if indicators else None
            state["macd_line"]         = indicators.get("macd_line") if indicators else None
            state["macd_signal"]       = indicators.get("macd_signal") if indicators else None
            state["macd_histogram"]    = indicators.get("macd_histogram") if indicators else None
            state["macd_bullish"]      = indicators.get("macd_bullish", False) if indicators else False
            state["ema_20"]            = indicators.get("ema_20") if indicators else None
            state["ema_50"]            = indicators.get("ema_50") if indicators else None
            state["price_above_ema20"] = indicators.get("price_above_ema20", False) if indicators else False
            state["ema20_above_ema50"] = indicators.get("ema20_above_ema50", False) if indicators else False
            state["rs_vs_btc"] = rs_vs_btc if rs_vs_btc is not None and not pd.isna(float(rs_vs_btc)) else 0.0
            supabase.table("coin_state").insert(state).execute()

    except Exception as e:
        log.error(f"update_coin_state failed for {product_id}: {e}")


# ─────────────────────────────────────────────
# STORAGE
# ─────────────────────────────────────────────

def store_signal(product_id: str, signal: dict, change_24hr: float):
    try:
        supabase.table("signals").insert({
            "product_id":   product_id,
            "timeframe":    signal["timeframe"],
            "price_change": signal["price_change"],
            "price":        signal["price"],
            "direction":    signal["direction"],
            "change_24hr":  change_24hr,
            "level":        signal.get("level", 1),
            "volume_ratio": signal.get("volume_ratio", 0),
            "l2_type":      signal.get("l2_type", ""),
        }).execute()
    except Exception as e:
        log.error(f"store_signal failed for {product_id}: {e}")


def store_momentum_history(product_id: str, change_24hr: float, price: float, volume: float = 0):
    try:
        supabase.table("momentum_history").insert({
            "product_id":  product_id,
            "change_24hr": change_24hr,
            "price":       price,
            "volume":      volume,
        }).execute()
    except Exception as e:
        log.error(f"store_momentum_history failed for {product_id}: {e}")


# ─────────────────────────────────────────────
# ALERT FORMATTERS
# ─────────────────────────────────────────────

def format_alert(product_id: str, signal: dict, change_24hr: float,
                 range_from_low: float = 0, accel_count: int = 0,
                 multi_leg_state: str | None = None) -> str:
    trend   = "📈" if change_24hr > 0 else "📉"
    l2_type = signal.get("l2_type", "")
    if l2_type == "volume":
        badge  = "🔴 L2 VOLUME"
        action = "\nAction    : Act now — volume confirmed"
    elif l2_type == "accel":
        badge  = "🟠 L2 ACCEL"
        action = "\nAction    : Watch — waiting for volume spike"
    else:
        badge  = "🟡" if signal.get("level", 1) < 2 else "🔴"
        action = ""
    intraday = f"\nIntraday  : +{range_from_low:.1f}% from 24hr low" if range_from_low >= 10 else ""

    # ── Momentum score ────────────────────────────────────────────────────────
    score     = calculate_momentum_score(signal, accel_count, multi_leg_state)
    score_str = f"\n{score_label(score)}"

    # ── TA indicators ─────────────────────────────────────────────────────────
    ta_lines = ""
    rsi  = signal.get("rsi")
    if rsi is not None:
        ta_lines += f"\n{rsi_label(float(rsi))}"
    if signal.get("macd_bullish") is not None:
        ta_lines += f" | {macd_label(signal['macd_bullish'], signal.get('macd_histogram', 0))}"
    if signal.get("price_above_ema20") is not None:
        ta_lines += f" | {ema_label(signal['price_above_ema20'], signal.get('ema20_above_ema50', False))}"
    rs = signal.get("rs_vs_btc")
    if rs is not None:
        ta_lines += f"\n{rs_btc_label(float(rs))}"
    ta_lines += f" | {fg_label(FEAR_GREED_VALUE, FEAR_GREED_LABEL)}"

    return (
        f"⚡ MOMENTUM SIGNAL\n"
        f"{badge} {signal['direction']} {product_id}\n"
        f"Timeframe : {signal['timeframe']}\n"
        f"Price Δ   : {signal['price_change']:+.2f}%\n"
        f"Volume    : {signal.get('volume_ratio', 0):.1f}x avg\n"
        f"24hr      : {trend} {change_24hr:+.2f}%"
        f"{intraday}"
        f"{score_str}"
        f"{ta_lines}"
        f"{action}\n"
        f"Price     : ${signal['price']:.6f}"
    )


def format_early_l2_alert(product_id: str, signal: dict, change_24hr: float,
                           range_from_low: float = 0) -> str:
    """Distinct alert for Dynamic L2 — clearly marked as early/unconfirmed."""
    intraday = f"\nIntraday  : +{range_from_low:.1f}% from 24hr low" if range_from_low >= 10 else ""

    # RSI warning — critical for early L2 entry quality
    rsi = signal.get("rsi", 50.0)
    rsi_line = f"\n{rsi_label(float(rsi))}"
    if rsi > 75:
        rsi_line += " ⚠️ high risk entry"

    rs = signal.get("rs_vs_btc")
    rs_line = f"\n{rs_btc_label(float(rs))}" if rs is not None else ""

    # Score for early L2 — uses accel_count from signal if available
    score     = calculate_momentum_score(signal, int(signal.get("accel_count") or 0))
    score_str = f"\n{score_label(score)}"

    return (
        f"⚡ EARLY L2 ⚠️ UNCONFIRMED — {product_id}\n"
        f"Timeframe : {signal.get('timeframe', '')}\n"
        f"Price Δ   : {signal.get('price_change', 0):+.2f}%\n"
        f"Volume    : {signal.get('volume_ratio', 0):.1f}x avg (dynamic threshold)\n"
        f"24hr      : {change_24hr:+.2f}%"
        f"{intraday}"
        f"{score_str}"
        f"{rsi_line}"
        f"{rs_line}\n"
        f"F&G       : {fg_label(FEAR_GREED_VALUE, FEAR_GREED_LABEL)}\n"
        f"Price     : ${signal.get('price', 0):.6f}\n"
        f"Action    : Strong runner detected early ⚠️ validate before entry"
    )


# ─────────────────────────────────────────────
# TP/SL ALERT FORMATTERS
# ─────────────────────────────────────────────

def format_tp1_alert(product_id: str, l2_price: float, price: float,
                     gain_pct: float, l2_type: str, accel_count: int) -> str:
    """Partial profit — sell % depends on explosive vs standard profile."""
    is_explosive  = accel_count >= EXPLOSIVE_ACCEL_MIN
    sell_pct      = TP1_SELL_EXPLOSIVE if is_explosive else TP1_SELL_STANDARD
    profile_label = "🔥 Explosive" if is_explosive else "Standard"
    type_badge    = "⚡ EARLY L2" if l2_type == "dynamic" else "L2"
    return (
        f"💰 TAKE PARTIAL PROFIT — {product_id}\n"
        f"Profile    : {profile_label} → sell {sell_pct}%\n"
        f"Entry ({type_badge}) : ${l2_price:.6f}\n"
        f"Now        : ${price:.6f} ({gain_pct:+.1f}%)\n"
        f"Action     : Sell {sell_pct}% now — lock in gains\n"
        f"Remainder  : Trailing stop activated (-{TRAILING_STOP_PCT:.0f}% from high)\n"
        f"Stop moved : Breakeven ${l2_price:.6f} — no more losing trades"
    )


def format_trailing_stop_alert(product_id: str, l2_price: float, price: float,
                                trailing_high: float, gain_pct: float,
                                is_grinder: bool) -> str:
    """Trailing stop hit on remainder post-TP1."""
    trail_pct = GRINDER_TRAIL_PCT if is_grinder else TRAILING_STOP_PCT
    drop_pct  = round((trailing_high - price) / trailing_high * 100, 1) if trailing_high > 0 else 0
    profile   = "🐢 Grinder" if is_grinder else "Standard"
    return (
        f"🔄 TRAILING STOP HIT — {product_id}\n"
        f"Profile    : {profile} (-{trail_pct:.0f}% trail)\n"
        f"Entry (L2) : ${l2_price:.6f}\n"
        f"Trail high : ${trailing_high:.6f} (highest close)\n"
        f"Now        : ${price:.6f} (-{drop_pct:.1f}% from high)\n"
        f"P&L        : {gain_pct:+.1f}% from entry\n"
        f"Action     : EXIT remainder — trend reversing"
    )


def format_hard_stop_alert(product_id: str, l2_price: float, price: float,
                            gain_pct: float, be_triggered: bool) -> str:
    """Hard stop — regular at -8% or breakeven stop if BE was triggered."""
    stop_type = "BREAKEVEN STOP" if be_triggered else "HARD STOP LOSS"
    emoji     = "🛡️" if be_triggered else "🛑"
    result    = "~0% — protected by BE trigger ✅" if be_triggered else f"{gain_pct:.1f}% loss"
    return (
        f"{emoji} {stop_type} — {product_id}\n"
        f"Entry (L2) : ${l2_price:.6f}\n"
        f"Now        : ${price:.6f} ({gain_pct:+.1f}%)\n"
        f"Action     : EXIT NOW — {'scratched at breakeven' if be_triggered else 'cut losses'}\n"
        f"Result     : {result}"
    )


def format_weak_signal_alert(product_id: str, l2_price: float, price: float,
                              gain_pct: float, hours: float) -> str:
    """Time stop — no momentum after 2 hours."""
    return (
        f"⚠️ WEAK SIGNAL EXIT — {product_id}\n"
        f"Entry (L2) : ${l2_price:.6f}\n"
        f"Now        : ${price:.6f} ({gain_pct:+.1f}%)\n"
        f"Held       : {hours:.1f} hours\n"
        f"Action     : EXIT — no momentum, free up capital"
    )


def format_intraday_alert(product_id: str, price: float, change_24hr: float,
                          range_from_low: float, full_range: float,
                          low_24h: float, high_24h: float) -> str:
    return (
        f"👀 INTRADAY MOVER {product_id}\n"
        f"From 24hr low : +{range_from_low:.1f}%\n"
        f"Full range    : {full_range:.1f}% (low→high)\n"
        f"24hr low      : ${low_24h:.6f}\n"
        f"24hr high     : ${high_24h:.6f}\n"
        f"Now           : ${price:.6f}\n"
        f"24hr Δ        : {change_24hr:+.2f}%\n"
        f"Action        : Watch for volume spike = entry"
    )


def format_24hr_alert(product_id: str, change_24hr: float, price: float) -> str:
    emoji = "📈 24HR GAINER" if change_24hr >= GAINER_24HR_THRESHOLD else "📉 24HR LOSER"
    return (
        f"{emoji} {product_id}\n"
        f"24hr Δ    : {change_24hr:+.2f}%\n"
        f"Price     : ${price:.6f}"
    )


def format_accel_alert(product_id: str, signal: dict) -> str:
    return (
        f"🔥 BUILDUP {product_id}\n"
        f"Timeframe : {signal['label']}\n"
        f"24hr was  : {signal['past_24hr']:+.2f}%\n"
        f"24hr now  : {signal['current_24hr']:+.2f}%\n"
        f"Accel     : +{signal['acceleration']:.2f}%\n"
        f"Price now : ${signal['current_price']:.6f}"
    )


def format_exit_alert(product_id: str, signal: dict, change_24hr: float) -> str:
    if change_24hr > 15:
        quality = "🟡 PULLBACK — 24hr still strong, watch for re-entry"
    elif change_24hr > 10:
        quality = "🟠 CAUTION — 24hr weakening, reduce position"
    else:
        quality = "🔴 EXIT — 24hr fading, get out"
    return (
        f"🔻 DUMP {product_id}\n"
        f"Timeframe : {signal['timeframe']}\n"
        f"Price Δ   : {signal['price_change']:+.2f}%\n"
        f"24hr      : {change_24hr:+.2f}%\n"
        f"Price     : ${signal['price']:.6f}\n"
        f"{quality}"
    )


def format_mega_pump_alert(product_id: str, threshold: int, change_24hr: float,
                           price: float, l2: str, accel_count: int) -> str:
    return (
        f"🚀 MEGA PUMP {product_id}\n"
        f"Milestone  : +{threshold}% crossed\n"
        f"24hr now   : +{change_24hr:.1f}%\n"
        f"Price      : ${price:.6f}\n"
        f"L2         : {l2} | Accel: {accel_count} stages"
    )


# ─────────────────────────────────────────────
# SUMMARIES
# ─────────────────────────────────────────────

def send_15min_summary():
    try:
        cutoff = (datetime.utcnow() - timedelta(minutes=15)).isoformat()
        res = supabase.table("coin_state")\
            .select("product_id,classification,change_24hr,current_price,"
                    "accel_count,l2_fired,l2_type,range_from_low,"
                    "coil_range_pct,peak_price,dump_fired,slow_grinder")\
            .gte("updated_at", cutoff)\
            .execute()

        if not res.data:
            return

        high_conviction = []
        building        = []
        watching        = []
        dumping         = []
        vol_watch       = []
        intraday_movers = []
        coiling         = []
        slow_grinders   = []

        for coin in res.data:
            c              = coin.get("classification", "")
            prob           = calc_probability(coin)
            ch24           = float(coin.get("change_24hr", 0) or 0)
            price          = float(coin.get("current_price", 0) or 0)
            accel          = "🔥" * min(coin.get("accel_count", 0) or 0, 4)
            l2             = coin.get("l2_fired", False)
            range_from_low = float(coin.get("range_from_low", 0) or 0)
            line           = f"{coin['product_id']} | 24hr: {ch24:+.1f}% | ${price:.4f} | Prob: {prob}% {accel}"

            if "HIGH CONVICTION" in c:
                high_conviction.append((prob, line))
            elif "BUILDING" in c:
                building.append((prob, line))
            elif "PULLBACK" in c or "DUMP" in c:
                dumping.append((ch24, line))
            elif "WATCHING" in c:
                watching.append((ch24, line))
            elif "INTRADAY" in c:
                intraday_movers.append((range_from_low,
                    f"{coin['product_id']} | +{range_from_low:.1f}% from low | 24hr: {ch24:+.1f}% | ${price:.4f}"))
            elif "COILING" in c:
                coil_pct = float(coin.get("coil_range_pct", 0) or 0)
                coiling.append((coil_pct,
                    f"{coin['product_id']} | Range: {coil_pct:.1f}% | 24hr: {ch24:+.1f}% | ${price:.4f}"))
            elif "SLOW GRINDER" in c:
                slow_grinders.append((ch24,
                    f"{coin['product_id']} | {c} | 24hr: {ch24:+.1f}% | ${price:.4f}"))

            if ch24 >= 15 and not l2 and (coin.get("accel_count", 0) or 0) >= 1:
                vol_watch.append((ch24,
                    f"{coin['product_id']} | 24hr: {ch24:+.1f}% | Waiting for volume spike {accel}"))

        if not any([high_conviction, building, watching, dumping, vol_watch, intraday_movers, coiling]):
            return

        high_conviction.sort(reverse=True)
        building.sort(reverse=True)
        watching.sort(reverse=True)
        dumping.sort(reverse=True)
        vol_watch.sort(reverse=True)
        intraday_movers.sort(reverse=True)
        coiling.sort(reverse=True)

        now = datetime.now(timezone.utc).astimezone(CDMX).strftime("%I:%M%p")
        msg = f"📊 15MIN MOVERS — {now}\n"
        msg += "─" * 25 + "\n"

        if high_conviction:
            msg += "\n🔴 HIGH CONVICTION\n"
            msg += "\n".join([l for _, l in high_conviction[:5]])
        if building:
            msg += "\n\n🟠 BUILDING\n"
            msg += "\n".join([l for _, l in building[:5]])
        if watching:
            msg += "\n\n🟡 WATCHING\n"
            msg += "\n".join([l for _, l in watching[:5]])
        if intraday_movers:
            msg += "\n\n👀 INTRADAY MOVERS (pumped from low)\n"
            msg += "\n".join([l for _, l in intraday_movers[:3]])
        if coiling:
            msg += "\n\n🔄 COILING (watch for breakout)\n"
            msg += "\n".join([l for _, l in coiling[:3]])
        if dumping:
            msg += "\n\n🔻 DUMPING/PULLBACK\n"
            msg += "\n".join([l for _, l in dumping[:5]])
        if vol_watch:
            msg += "\n\n🔍 WATCH FOR L2 (volume spike incoming?)\n"
            msg += "\n".join([l for _, l in vol_watch[:3]])
        if slow_grinders:
            msg += "\n\n🐢 SLOW GRINDERS\n"
            msg += "\n".join([l for _, l in slow_grinders[:3]])

        # ⚡ Dynamic L2 — query signals table for recent dynamic fires
        try:
            dl2_cutoff = (datetime.utcnow() - timedelta(minutes=15)).isoformat()
            dl2_res = supabase.table("signals")\
                .select("product_id, price_change, change_24hr, price")\
                .eq("l2_type", "dynamic")\
                .gte("triggered_at", dl2_cutoff)\
                .execute()
            if dl2_res.data:
                early_lines = []
                for r in dl2_res.data:
                    pid = r["product_id"]
                    chg = float(r.get("price_change", 0) or 0)
                    c24 = float(r.get("change_24hr", 0) or 0)
                    pr  = float(r.get("price", 0) or 0)
                    early_lines.append((c24, f"{pid} | 24hr: {c24:+.1f}% | Δ {chg:+.1f}% | ${pr:.4f}"))
                early_lines.sort(reverse=True)
                msg += "\n\n⚡ EARLY L2 ⚠️ UNCONFIRMED (validate before entry)\n"
                msg += "\n".join([l for _, l in early_lines[:3]])
        except Exception as e:
            log.error(f"Dynamic L2 summary query failed: {e}")

        send_telegram_alert(msg)
        log.info("15min summary sent")

    except Exception as e:
        log.error(f"15min summary failed: {e}")


def send_1hour_summary():
    try:
        cutoff = (datetime.utcnow() - timedelta(hours=1)).isoformat()
        res = supabase.table("coin_state")\
            .select("product_id,change_24hr,current_price,l2_fired,l2_type,"
                    "dump_fired,range_from_low,l2_price,accel_count,"
                    "dump_price,peak_price")\
            .gte("updated_at", cutoff)\
            .order("change_24hr", desc=True)\
            .execute()

        if not res.data:
            return

        top_gainers     = [c for c in res.data if float(c.get("change_24hr", 0) or 0) >= 15][:5]
        active_pumps    = [c for c in res.data if c.get("l2_fired") and not c.get("dump_fired")][:5]
        pullbacks       = [c for c in res.data if c.get("dump_fired") and float(c.get("change_24hr", 0) or 0) > 10][:3]
        cooling         = [c for c in res.data if float(c.get("change_24hr", 0) or 0) < 10 and c.get("l2_fired")][:3]
        intraday_movers = [c for c in res.data
                          if float(c.get("range_from_low", 0) or 0) >= INTRADAY_RANGE_THRESHOLD
                          and float(c.get("change_24hr", 0) or 0) < 15][:3]
        low_vol_gainers = [c for c in res.data
                          if float(c.get("change_24hr", 0) or 0) >= 20
                          and not c.get("l2_fired")
                          and get_avg_volume_ratio(c["product_id"]) < LOW_VOLUME_THRESHOLD][:3]

        now = datetime.now(timezone.utc).astimezone(CDMX).strftime("%I:%M%p")
        msg = f"📈 1HR SUMMARY — {now}\n"
        msg += "─" * 25 + "\n"

        if top_gainers:
            msg += "\n🏆 TOP 24HR GAINERS\n"
            for c in top_gainers:
                prob = calc_probability(c)
                msg += f"{c['product_id']} | 24hr: {float(c['change_24hr']):+.1f}% | ${float(c['current_price']):.4f} | Prob: {prob}%\n"

        if active_pumps:
            msg += "\n🚀 ACTIVE PUMPS\n"
            for c in active_pumps:
                accel = "🔥" * min(c.get("accel_count", 0) or 0, 4)
                msg += f"{c['product_id']} L2 @ ${float(c.get('l2_price', 0) or 0):.4f} {accel}\n"

        if intraday_movers:
            msg += "\n👀 INTRADAY MOVERS (low 24hr% but moved big)\n"
            for c in intraday_movers:
                rfl = float(c.get("range_from_low", 0) or 0)
                msg += f"{c['product_id']} | +{rfl:.1f}% from low | 24hr: {float(c['change_24hr']):+.1f}% — watch for L2\n"

        if pullbacks:
            msg += "\n🔻 PULLBACKS (watch re-entry)\n"
            for c in pullbacks:
                msg += f"{c['product_id']} dumped @ ${float(c.get('dump_price', 0) or 0):.4f} | 24hr {float(c['change_24hr']):+.1f}%\n"

        if cooling:
            msg += "\n⚫ COOLING OFF\n"
            for c in cooling:
                msg += f"{c['product_id']} {float(c['change_24hr']):+.1f}% 24hr\n"

        if low_vol_gainers:
            msg += "\n⚠ LOW VOLUME GAINERS (no confirmation yet)\n"
            for c in low_vol_gainers:
                msg += f"{c['product_id']} | 24hr: {float(c['change_24hr']):+.1f}% | Vol avg < 0.5x — watch for spike\n"

        send_telegram_alert(msg)
        log.info("1hr summary sent")

    except Exception as e:
        log.error(f"1hr summary failed: {e}")


# ─────────────────────────────────────────────
# NEW LISTINGS
# ─────────────────────────────────────────────

def check_new_listings():
    global PRODUCTS
    try:
        new_products = fetch_all_active_products()
        with _products_lock:
            current_set  = set(PRODUCTS)
        new_set      = set(new_products)
        new_listings = new_set - current_set

        if new_listings and len(current_set) > 0:
            for product in new_listings:
                log.info(f"🆕 New listing detected: {product} — added to scanner")
        with _products_lock:
            PRODUCTS = new_products
        log.info(f"Products updated — {len(PRODUCTS)} pairs")
    except Exception as e:
        log.error(f"check_new_listings failed: {e}")


def refresh_products():
    global PRODUCTS
    try:
        new_products = fetch_all_active_products()
        with _products_lock:
            PRODUCTS = new_products
        log.info(f"Daily refresh — {len(PRODUCTS)} pairs loaded")
        send_telegram_alert(
            f"🔄 DAILY PRODUCT REFRESH\n"
            f"Pairs loaded : {len(PRODUCTS)}\n"
            f"Time         : {datetime.now().strftime('%I:%M %p')}"
        )
    except Exception as e:
        log.error(f"refresh_products failed: {e}")


# ─────────────────────────────────────────────
# CLEANUP
# ─────────────────────────────────────────────

def cleanup_old_data():
    try:
        supabase.table("prices").delete()\
            .lt("timestamp", (datetime.utcnow() - timedelta(hours=48)).isoformat()).execute()
        supabase.table("momentum_history").delete()\
            .lt("recorded_at", (datetime.utcnow() - timedelta(days=2)).isoformat()).execute()
        supabase.table("coin_state").delete()\
            .lt("updated_at", (datetime.utcnow() - timedelta(hours=48)).isoformat()).execute()
        supabase.table("signals").delete()\
            .lt("triggered_at", (datetime.utcnow() - timedelta(days=90)).isoformat()).execute()
        supabase.table("daily_snapshots").delete()\
            .lt("date", (datetime.utcnow().date() - timedelta(days=30)).isoformat()).execute()
        log.info("Cleanup complete")
    except Exception as e:
        log.error(f"Cleanup failed: {e}")


# ─────────────────────────────────────────────
# MAIN CYCLE
# ─────────────────────────────────────────────

PRODUCTS  = []
FIRST_RUN = True

def update_prices_and_signals():
    global PRODUCTS, FIRST_RUN
    if not PRODUCTS:
        PRODUCTS = fetch_all_active_products()
        log.info(f"Loaded {len(PRODUCTS)} products")

    if not FIRST_RUN:
        check_new_listings()
    FIRST_RUN = False  # ← bug fix: must be outside the if block

    # Fetch caches ONCE for entire cycle — egress optimization
    momentum_cache = fetch_momentum_cache()
    state_cache    = fetch_state_cache()   # accel_count + coiling per coin

    # Snapshot PRODUCTS under lock — safe iteration while refresh runs on another thread
    with _products_lock:
        products_snapshot = list(PRODUCTS)

    log.info(f"Scanning {len(products_snapshot)} products...")

    pump_alerts     = []
    dump_alerts     = []
    gainer_alerts   = []
    loser_alerts    = []
    accel_alerts    = []
    intraday_alerts = []
    early_l2_alerts = []   # ⚡ Dynamic L2 — separate track, separate cooldown
    signal_count    = 0

    # Per-coin L2 deduplication — collect best signal per coin, not one per timeframe
    # Without this, a single L2 event sends 4 identical Telegram messages (5min/15min/30min/1hr)
    coin_best_pump = {}   # product_id → (price_change, alert_str) — highest vol_ratio wins
    coin_best_dump = {}   # product_id → (abs_change, alert_str)

    for product in products_snapshot:

        details = fetch_product_details(product)
        if not details or not details.get("price"):
            time.sleep(0.1)
            continue

        price       = details["price"]
        change_24hr = details["change_24hr"]
        volume_24h  = details["volume_24h"]

        store_price(product, price, volume_24h)

        # ── Conditional momentum_history — egress optimization ───────────────
        # Only store coins that are actively moving. Neutral coins (flat 24hr,
        # no L2, no accel) don't need minute-by-minute history.
        # Reduces momentum_history table size by ~80%, cutting cache egress.
        existing_state = state_cache.get(product, {})
        is_active = (
            change_24hr >= 2.0
            or change_24hr <= -5.0
            or (existing_state.get("accel_count") or 0) > 0
            or existing_state.get("l2_fired")
            or existing_state.get("coiling")
            or existing_state.get("slow_grinder")
            # Include quiet coins that could be coiling (low 24hr, decent volume)
            or (abs(change_24hr) < 5.0 and volume_24h >= 1_000_000)
        )
        if is_active:
            store_momentum_history(product, change_24hr, price, volume_24h)

        low_liquidity = volume_24h < MIN_VOLUME_24H

        # ── Track BTC as market reference ────────────────────────────────────
        global BTC_CHANGE_24HR
        if product == "BTC-USD":
            BTC_CHANGE_24HR = change_24hr

        # ── Acceleration (uses in-memory cache) ──────────────────────────────
        accel_signals = check_acceleration(product, change_24hr, price, momentum_cache)
        for accel in accel_signals:
            signal_count += 1
            accel_alerts.append((accel["acceleration"], product, format_accel_alert(product, accel)))

        # ── 24hr Gainer / Loser ──────────────────────────────────────────────
        if change_24hr >= GAINER_24HR_THRESHOLD:
            signal_count += 1
            store_signal(product, {
                "timeframe": "24hour", "price_change": change_24hr,
                "price": price, "direction": "📈 GAINER", "level": 1, "volume_ratio": 0, "l2_type": "",
            }, change_24hr)
            gainer_alerts.append((change_24hr, product, format_24hr_alert(product, change_24hr, price)))

        elif change_24hr <= LOSER_24HR_THRESHOLD:
            signal_count += 1
            store_signal(product, {
                "timeframe": "24hour", "price_change": change_24hr,
                "price": price, "direction": "📉 LOSER", "level": 1, "volume_ratio": 0, "l2_type": "",
            }, change_24hr)
            loser_alerts.append((change_24hr, product, format_24hr_alert(product, change_24hr, price)))

        # ── Short-term Momentum ──────────────────────────────────────────────
        df            = fetch_candles(product, limit=250)
        latest_signal = None

        # Initialize so VS Code and runtime both see these always defined
        indicators        = {}
        rs_vs_btc         = 0.0
        recent_close_high = price

        if not df.empty:
            df_24hr        = df.tail(1440)
            high_24h       = float(df_24hr["high"].max())
            low_24h        = float(df_24hr["low"].min())
            range_from_low = round(((price - low_24h) / low_24h * 100), 2) if low_24h > 0 else 0.0
            full_range     = round(((high_24h - low_24h) / low_24h * 100), 2) if low_24h > 0 else 0.0
        else:
            high_24h = low_24h = range_from_low = full_range = 0.0

        # ── Intraday mover detection ─────────────────────────────────────────
        # Require accel_count >= 1 — pure price range without momentum confirmation
        # generates too many false alerts on thin coins moving sideways
        if (range_from_low >= INTRADAY_RANGE_THRESHOLD
                and change_24hr < GAINER_24HR_THRESHOLD
                and change_24hr > -5
                and (existing_state.get("accel_count") or 0) >= 1):
            signal_count += 1
            intraday_alerts.append((
                range_from_low, product,
                format_intraday_alert(product, price, change_24hr,
                                      range_from_low, full_range, low_24h, high_24h)
            ))

        if not df.empty:
            # ── Pre-compute Dynamic L2 inputs once per coin ───────────────────
            # existing_state already fetched from state_cache above
            accel_count_now = (existing_state.get("accel_count") or 0) + len(accel_signals)
            coiling_now     = bool(existing_state.get("coiling", False))

            if len(df) >= 31:
                fresh_price        = float(df["close"].iloc[-31])
                price_change_30min = (price - fresh_price) / fresh_price * 100 if fresh_price > 0 else 0.0
            else:
                price_change_30min = 0.0

            vol_series   = df["volume"].iloc[-4:].tolist() if len(df) >= 4 else []
            vol_trend_up = is_volume_trending_up(vol_series)

            # ── TA indicators — calculated once, used everywhere ──────────────
            indicators  = calculate_indicators(df)
            rs_vs_btc = round(change_24hr - BTC_CHANGE_24HR, 2) if not (pd.isna(change_24hr) or pd.isna(BTC_CHANGE_24HR)) else 0.0

            # ── Intra-cycle high — wick-filtered highest close in last 8 min ──
            # Passed to update_coin_state so peak_price captures intra-poll spikes
            # without being fooled by rogue wicks (uses close not high)
            recent_close_high = float(df["close"].iloc[-15:].max()) if len(df) >= 15 else price

            for label, config in MOMENTUM_CONFIGS.items():
                signal = check_momentum(df, config, label, change_24hr, low_liquidity,
                                        accel_count=accel_count_now,
                                        price_change_30min=price_change_30min,
                                        vol_trend_up=vol_trend_up,
                                        coiling=coiling_now,
                                        rs_vs_btc=rs_vs_btc)
                if signal:
                    signal_count += 1
                    # ── Attach indicators to signal for alert formatting ───────
                    signal["rsi"]               = indicators["rsi"]
                    signal["macd_bullish"]      = indicators["macd_bullish"]
                    signal["macd_histogram"]    = indicators["macd_histogram"]
                    signal["price_above_ema20"] = indicators["price_above_ema20"]
                    signal["ema20_above_ema50"] = indicators["ema20_above_ema50"]
                    signal["rs_vs_btc"]         = rs_vs_btc
                    store_signal(product, signal, change_24hr)
                    latest_signal = signal
                    log.info(
                        f"L{signal['level']} [{label}] {product}: "
                        f"{signal['price_change']:+.2f}% | "
                        f"Vol: {signal['volume_ratio']}x | "
                        f"24hr: {change_24hr:+.2f}% | "
                        f"RSI: {indicators['rsi']:.0f}"
                        + (" [DYNAMIC]" if signal.get("is_dynamic") else "")
                    )
                    if signal["price_change"] > 0:
                        if signal.get("is_dynamic"):
                            early_l2_alerts.append((
                                signal["price_change"], product,
                                format_early_l2_alert(product, signal, change_24hr, range_from_low)
                            ))
                        else:
                            # Keep only best timeframe signal per coin per cycle
                            # Best = highest volume_ratio (strongest confirmation)
                            existing_best = coin_best_pump.get(product)
                            vol = signal.get("volume_ratio", 0)
                            if not existing_best or vol > existing_best[0]:
                                multi_leg = (existing_state.get("multi_leg_state")
                                             if existing_state else None)
                                coin_best_pump[product] = (
                                    vol,
                                    signal["price_change"],
                                    format_alert(product, signal, change_24hr,
                                                 range_from_low, accel_count_now,
                                                 multi_leg)
                                )
                    else:
                        # Keep only best dump signal per coin per cycle
                        existing_dump = coin_best_dump.get(product)
                        vol = signal.get("volume_ratio", 0)
                        if not existing_dump or vol > existing_dump[0]:
                            coin_best_dump[product] = (
                                vol,
                                abs(signal["price_change"]),
                                format_exit_alert(product, signal, change_24hr)
                            )
                        # ── Hall of Fame insert — profitable dump exit ────────────────────────
                        try:
                            l2p  = float((existing_state or {}).get("l2_price") or 0)
                            peak = float((existing_state or {}).get("peak_price") or 0)
                            gain = round((price - l2p) / l2p * 100, 1) if l2p > 0 else 0
                            if l2p > 0 and price > l2p and gain >= 5.0 and not (existing_state or {}).get("tp1_hit"):
                                supabase.table("hall_of_fame").insert({
                                    "product_id":     product,
                                    "l2_type":        str((existing_state or {}).get("l2_type") or "volume"),
                                    "l2_fired_at":    str((existing_state or {}).get("l2_fired_at") or ""),
                                    "l2_price":       l2p,
                                    "peak_price":     peak,
                                    "peak_gain":      round((peak - l2p) / l2p * 100, 1) if l2p > 0 else 0,
                                    "dump_price":     price,
                                    "dump_exit_gain": gain,
                                    "tp1_hit":        False,
                                    "dump_fired":     True,
                                    "accel_count":    int((existing_state or {}).get("accel_count") or 0),
                                    "rsi":            (existing_state or {}).get("rsi"),
                                    "rs_vs_btc":      (existing_state or {}).get("rs_vs_btc"),
                                    "exit_type":      "DUMP_EXIT",
                                    "exit_gain":      gain,
                                }).execute()
                                log.info(f"🏆 Hall of Fame: {product} DUMP_EXIT +{gain}%")
                        except Exception as e:
                            log.warning(f"Hall of Fame insert failed ({product}): {e}")
            check_volume_spike(product, df, change_24hr, price)
            check_tx_spike(product, df, change_24hr, price)

        # ── TP/SL position management ────────────────────────────────────────
        # Runs before update_coin_state so state_cache reflects pre-update values
        existing_for_tpsl = state_cache.get(product, {})
        check_tp_sl(product, price, existing_for_tpsl, df if not df.empty else None)

        # ── Update coin state ────────────────────────────────────────────────
        avg_volume_6hr = round(float(df["volume"].iloc[-360:].mean()), 4) if not df.empty and len(df) >= 10 else 0.0
        indicators_to_write = indicators if not df.empty and indicators else None
        update_coin_state(product, price, change_24hr, latest_signal, accel_signals,
                         range_from_low, full_range, high_24h, low_24h, low_liquidity,
                         avg_volume_6hr, intra_cycle_high=recent_close_high,
                         indicators=indicators_to_write, rs_vs_btc=rs_vs_btc if not df.empty else None,
                         existing=state_cache.get(product))

        # ── Mega pump milestones ─────────────────────────────────────────────
        for threshold in MEGA_PUMP_THRESHOLDS:
            if change_24hr >= threshold:
                if should_alert(product, f"mega_{threshold}"):
                    # Don't fire mega pump if position already closed
                    # (e.g. hard stop at -12% then coin rebounds — confusing)
                    pos_state = state_cache.get(product, {})
                    if pos_state.get("position_closed") or pos_state.get("sl_hit"):
                        continue
                    state_q = state_cache.get(product, {})
                    l2_str  = "Yes" if state_q.get("l2_fired") else "No"
                    accel_c = state_q.get("accel_count", 0) or 0
                    send_telegram_alert(format_mega_pump_alert(
                        product, threshold, change_24hr, price, l2_str, accel_c))
                    log.info(f"Mega pump alert: {product} +{threshold}%")

        time.sleep(0.15)

    # ── Flatten per-coin best signals into alert lists ────────────────────────
    for product_id, (vol, price_change, alert) in coin_best_pump.items():
        pump_alerts.append((price_change, product_id, alert))
    for product_id, (vol, price_change, alert) in coin_best_dump.items():
        dump_alerts.append((price_change, product_id, alert))

    # ── Send Alerts ──────────────────────────────────────────────────────────
    accel_alerts.sort(key=lambda x: x[0], reverse=True)
    for accel_val, product_id, alert in accel_alerts:
        label = "accel_30min"
        for label_key in ["30min", "1hour", "3hour", "8hour"]:
            if label_key in alert:
                label = f"accel_{label_key}"
                break
        if should_alert(product_id, label):
            send_telegram_alert(alert)
            log.info(f"Accel alert sent: {product_id}")

    # 24hour gainer/loser alerts removed — too noisy, zero actionability
    # Signals are still stored in DB for historical analysis
    # The 15min and 1hr summaries still surface top gainers

    intraday_alerts.sort(key=lambda x: x[0], reverse=True)
    for rfl, product_id, alert in intraday_alerts[:5]:
        if should_alert(product_id, "intraday"):
            send_telegram_alert(alert)
            log.info(f"Intraday alert sent: {product_id} +{rfl:.1f}% from low")

    pump_alerts.sort(key=lambda x: x[0], reverse=True)
    for change, product_id, alert in pump_alerts:
        if change >= PUMP_ALERT_THRESHOLD and should_alert(product_id, "pump"):
            if FEAR_GREED_VALUE <= 20:
                log.info(f"F&G {FEAR_GREED_VALUE} — Extreme Fear, pump alert suppressed for {product_id}")
                continue
            pump_state = state_cache.get(product_id, {})
            if not pump_state.get("l2_fired"):
                continue  # no L2 — skip
            l2_at = pump_state.get("l2_fired_at")
            if l2_at:
                l2_age_minutes = (
                    datetime.utcnow() -
                    datetime.fromisoformat(l2_at.replace("Z", "+00:00"))
                    .replace(tzinfo=None)
                ).total_seconds() / 60
                if l2_age_minutes > 30:
                    continue  # L2 too old — skip
            streak = state_cache.get(product_id, {}).get("l2_streak", 0)
            if streak < L2_STREAK_THRESHOLD:
                log.info(f"L2 streak {streak} below threshold — alert held for {product_id}")
                continue
            send_telegram_alert(alert)

    dump_alerts.sort(key=lambda x: x[0], reverse=True)
    for change, product_id, alert in dump_alerts:
        if change >= DUMP_ALERT_THRESHOLD and should_alert(product_id, "dump"):
            send_telegram_alert(alert)

    # ⚡ Early L2 (Dynamic) — top N per cycle, own cooldown
    early_l2_alerts.sort(key=lambda x: x[0], reverse=True)
    for change, product_id, alert in early_l2_alerts[:EARLY_L2_MAX_PER_CYCLE]:
        if change >= PUMP_ALERT_THRESHOLD and should_alert(product_id, "early_l2"):
            if FEAR_GREED_VALUE <= 20:
                log.info(f"F&G {FEAR_GREED_VALUE} — Extreme Fear, early L2 alert suppressed for {product_id}")
                continue
            # Note: pump cooldown intentionally NOT stamped here.
            # A standard L2 firing shortly after = volume confirmation of the early signal.
            # That confirmation alert is valuable — don't suppress it.
            send_telegram_alert(alert)
            log.info(f"⚡ Early L2 alert sent: {product_id} +{change:.1f}%")

    cleanup_old_data()
    log.info(f"Cycle complete — {signal_count} signal(s) across {len(PRODUCTS)} products")


# ─────────────────────────────────────────────
# DEDICATED SCANS (separate scheduled jobs)
# ─────────────────────────────────────────────

def fetch_coiling_cache() -> dict:
    """
    Batch fetch 25hr of momentum_history for all coins in ONE query.
    Replaces 231 individual queries in run_coiling_scan.
    Same egress but massively fewer round trips.
    """
    try:
        cutoff = (datetime.utcnow() - timedelta(hours=25)).isoformat()
        res = supabase.table("momentum_history")\
            .select("product_id, price, recorded_at")\
            .gte("recorded_at", cutoff)\
            .order("recorded_at", desc=False)\
            .execute()
        cache = {}
        for row in (res.data or []):
            cache.setdefault(row["product_id"], []).append(row)
        log.info(f"Coiling cache loaded — {len(res.data or [])} rows for {len(cache)} coins")
        return cache
    except Exception as e:
        log.error(f"fetch_coiling_cache failed: {e}")
        return {}


def run_daily_snapshot():
    """Midnight cron — write one snapshot row per coin for today."""
    log.info("📸 Starting daily snapshot...")
    with _products_lock:
        products_snapshot = list(PRODUCTS)
    snapshot_count = 0
    for product in products_snapshot:
        try:
            details = fetch_product_details(product)
            if not details or not details.get("price"):
                continue
            write_daily_snapshot(
                product,
                details["price"],
                details["change_24hr"],
                details["volume_24h"],
            )
            snapshot_count += 1
            time.sleep(0.05)
        except Exception as e:
            log.error(f"Daily snapshot failed for {product}: {e}")
    log.info(f"📸 Daily snapshot complete — {snapshot_count} coins written")


def run_coiling_scan():
    log.info("🔄 Starting coiling scan...")
    with _products_lock:
        products_snapshot = list(PRODUCTS)

    # Batch fetch all coins' 24hr history — one query instead of 231
    coiling_cache = fetch_coiling_cache()

    for product in products_snapshot:
        try:
            details = fetch_product_details(product)
            if not details or not details.get("price"):
                continue
            price       = details["price"]
            change_24hr = details["change_24hr"]
            volume_24h  = details["volume_24h"]

            # Pass pre-fetched history into check_coiling
            product_history = coiling_cache.get(product, [])
            check_coiling(product, price, change_24hr, volume_24h,
                          history=product_history)
            time.sleep(0.05)
        except Exception as e:
            log.error(f"Coiling scan failed for {product}: {e}")
    log.info("🔄 Coiling scan complete")


def run_slow_grinder_scan():
    log.info("🐢 Starting slow grinder scan...")
    with _products_lock:
        products_snapshot = list(PRODUCTS)

    # Batch fetch all coins' daily snapshots — one query instead of 231
    snapshots_cache = fetch_all_daily_snapshots(days=7)

    # Collect HH/HL alerts here — send only top 5 at end to avoid 50-alert dumps
    hh_hl_pending = []

    for product in products_snapshot:
        try:
            details = fetch_product_details(product)
            if not details or not details.get("price"):
                continue
            price       = details["price"]
            change_24hr = details["change_24hr"]
            volume_24h  = details["volume_24h"]

            # Write today's snapshot (upsert — safe to call multiple times)
            write_daily_snapshot(product, price, change_24hr, volume_24h)

            daily_data = snapshots_cache.get(product, [])
            check_slow_grinder(product, price, change_24hr, daily_data,
                               hh_hl_pending=hh_hl_pending)
            time.sleep(0.05)
        except Exception as e:
            log.error(f"Slow grinder scan failed for {product}: {e}")

    # Send top 5 HH/HL alerts sorted by quality score
    hh_hl_pending.sort(key=lambda x: x[0], reverse=True)
    sent = 0
    for quality, product_id, alert in hh_hl_pending:
        if sent >= 5:
            break
        send_telegram_alert(alert)
        sent += 1
        time.sleep(0.5)

    log.info(f"🐢 Slow grinder scan complete — {sent} HH/HL alerts sent")


# ─────────────────────────────────────────────
# SCHEDULER
# ─────────────────────────────────────────────

scheduler = BackgroundScheduler()

scheduler.add_job(
    update_prices_and_signals,
    "interval", minutes=7, id="momentum_scan",
    next_run_time=datetime.now(), misfire_grace_time=60,
    max_instances=1    # prevent overlapping runs if cycle exceeds 7 min
)
scheduler.add_job(
    send_15min_summary,
    "interval", minutes=15, id="summary_15min",
    misfire_grace_time=60
)
scheduler.add_job(
    send_1hour_summary,
    "interval", hours=1, id="summary_1hour",
    misfire_grace_time=60
)
# ── Cron timezone note ───────────────────────────────────────────────────────
# APScheduler defaults to the server's OS timezone (UTC on Railway/Heroku/AWS).
# All cron jobs below run in UTC intentionally — UTC midnight = global crypto
# daily candle close, which is the correct boundary for daily_snapshots and
# product refresh. CDMX users will see these fire at ~6:05 PM local time.
# To run at CDMX midnight instead, add: timezone=CDMX to each add_job call.
# ─────────────────────────────────────────────────────────────────────────────

scheduler.add_job(
    refresh_products,
    "cron", hour=0, minute=0, id="refresh_products",
    misfire_grace_time=60
)
scheduler.add_job(
    run_daily_snapshot,
    "cron", hour=0, minute=5, id="daily_snapshot",   # 5 min after midnight UTC, after product refresh
    misfire_grace_time=300
)
scheduler.add_job(
    fetch_fear_greed,
    "cron", hour=0, minute=10, id="fear_greed_refresh",   # daily, after snapshot
    misfire_grace_time=300
)
scheduler.add_job(
    run_slow_grinder_scan,
    "interval", hours=6, id="slow_grinder_scan",
    misfire_grace_time=300
)
scheduler.add_job(
    run_coiling_scan,
    "interval", hours=2, id="coiling_scan",   # every 2hr — coiling is slow, 30min was overkill
    misfire_grace_time=300
)

scheduler.start()

# ── Startup fetches ───────────────────────────────────────────────────────────
fetch_fear_greed()   # populate F&G immediately — don't wait for midnight cron

log.info("🚀 Momentum tracker started — 7 min cycle")
log.info("Press Ctrl+C to stop")

try:
    while True:
        time.sleep(60)
except (KeyboardInterrupt, SystemExit):
    scheduler.shutdown()
    log.info("🛑 Tracker stopped")