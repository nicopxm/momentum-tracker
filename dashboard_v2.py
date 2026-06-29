import math
import streamlit as st
import pandas as pd
from supabase import create_client, Client
from datetime import datetime, timedelta, timezone
import os
from dotenv import load_dotenv
import time as time_module
from streamlit_autorefresh import st_autorefresh
import requests

st_autorefresh(interval=60000, key="autorefresh")

load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))

CDMX = timezone(timedelta(hours=-6))

st.set_page_config(page_title="Momentum — Coinbase Signal Tracker", page_icon="M", layout="wide")

_valid_pages = {"Dashboard", "About", "HowItWorks", "Contact"}
if "page" not in st.session_state:
    _qp = st.query_params.get("page", "Dashboard")
    st.session_state.page = _qp if _qp in _valid_pages else "Dashboard"
if "dark_mode" not in st.session_state: st.session_state.dark_mode = False

dm = st.session_state.dark_mode

LIGHT_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,400;0,600;0,700;1,400&family=Outfit:wght@300;400;500;600&family=JetBrains+Mono:wght@400;500&display=swap');
:root {
  --bg:#F7F4EE; --bg2:#EDE9DF; --card:#FFFFFF; --navy:#0E1B2E;
  --gold:#B8923A; --gold2:#D4A853; --green:#1A7A4A; --red:#9B2335;
  --muted:#6B7280; --border:#DDD8CE; --text:#0E1B2E; --subtext:#6B7280;
}
.stApp {
    background-color: #eef2ee !important;
    background-image:
        url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='40' height='40'%3E%3Cpath d='M 40 0 L 0 0 0 40' fill='none' stroke='rgba(0,60,30,0.06)' stroke-width='0.5'/%3E%3C/svg%3E"),
        linear-gradient(135deg, #f5faf5 0%, #eff4ee 50%, #e6ede6 100%) !important;
    background-repeat: repeat, no-repeat !important;
    background-size: 40px 40px, cover !important;
    background-attachment: scroll, fixed !important;
}
"""

DARK_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,400;0,600;0,700;1,400&family=Outfit:wght@300;400;500;600&family=JetBrains+Mono:wght@400;500&display=swap');
:root {
  --bg:#0a0a0f; --bg2:#12121a; --card:#12121a; --navy:#0E1B2E;
  --gold:#D4A853; --gold2:#D4A853; --green:#00ff88; --red:#ff4444;
  --muted:#888888; --border:#1e1e2e; --text:#e8e8f0; --subtext:#888888;
}
.stApp {
    background-color: #07090f !important;
    background-image:
        url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='40' height='40'%3E%3Cpath d='M 40 0 L 0 0 0 40' fill='none' stroke='rgba(0,255,136,0.04)' stroke-width='0.5'/%3E%3C/svg%3E"),
        linear-gradient(135deg, #0d1520 0%, #07090f 55%, #040609 100%) !important;
    background-repeat: repeat, no-repeat !important;
    background-size: 40px 40px, cover !important;
    background-attachment: scroll, fixed !important;
}
"""

SHARED_CSS = """
* { font-family: 'Outfit', sans-serif; }
.stApp {
    color: var(--text) !important;
}
#MainMenu, footer, header { visibility: hidden; }
.block-container { padding: 1rem 3rem 3rem 3rem !important; max-width: 100% !important; }

div[data-testid="stTabs"] [data-baseweb="tab-list"] {
    display:flex !important; width:100% !important;
    justify-content:space-between !important;
    background:linear-gradient(145deg, var(--card) 0%, rgba(184,146,58,0.06) 100%) !important;
    border:1px solid var(--border) !important;
    border-radius:12px !important; padding:6px !important;
    gap:0px !important; margin-bottom:24px !important;
    box-shadow: 0 0 6px 1px rgba(184,146,58,0.25) !important;
    transition: box-shadow 0.2s !important;
}
div[data-testid="stTabs"] [data-baseweb="tab"] {
    flex:1 !important; text-align:center !important;
    background-color:transparent !important;
    color:var(--subtext) !important;
    font-size:11px !important; font-weight:600 !important;
    text-transform:uppercase !important; letter-spacing:0.1em !important;
    border:none !important; padding:14px 0 !important;
    position:relative !important; display:flex !important;
    justify-content:center !important; font-family:'Outfit',sans-serif !important;
    transition: color 0.2s !important;
}
div[data-testid="stTabs"] [data-baseweb="tab"]:not(:last-child)::after {
    content:''; position:absolute; right:0; top:25%; height:50%; width:1px;
    background-color:var(--border);
}
div[data-testid="stTabs"] [data-baseweb="tab"]:hover {
    color: var(--gold) !important;
    background: rgba(184,146,58,0.07) !important;
    border-radius: 6px !important;
}
div[data-testid="stTabs"] [aria-selected="true"] {
    color:var(--gold) !important;
    background:rgba(184,146,58,0.07) !important;
    border-radius:8px !important;
    font-size:12px !important; letter-spacing:0.12em !important;
    text-shadow: none !important;
}
div[data-testid="stTabs"] [data-baseweb="tab-highlight"],
div[data-testid="stTabs"] [data-baseweb="tab-border"] { display:none !important; }

div.stButton > button {
    background:linear-gradient(145deg, var(--card) 0%, rgba(184,146,58,0.07) 100%) !important;
    color:var(--text) !important;
    border:1px solid var(--border) !important; border-radius:8px !important;
    font-weight:600 !important; font-size:12px !important; padding:6px 16px !important;
    font-family:'Outfit',sans-serif !important; transition:all 0.2s !important;
    box-shadow: 0 0 6px 1px rgba(184,146,58,0.25) !important;
}
div.stButton > button:hover { border-color:var(--gold) !important; color:var(--gold) !important; box-shadow: 0 0 12px 3px rgba(184,146,58,0.5) !important; }
div[data-testid="stButton-nav_active"] > button {
    border-color:var(--gold) !important; color:var(--gold) !important;
    background:linear-gradient(145deg, var(--card) 0%, rgba(184,146,58,0.15) 100%) !important;
    box-shadow: 0 0 10px 2px rgba(184,146,58,0.4) !important;
}

.hero-block {
    background:var(--navy); border-radius:16px; padding:48px 56px;
    margin-bottom:28px; color:white; border-bottom:3px solid var(--gold);
    position:relative; overflow:hidden;
}
.hero-block::after {
    content:''; position:absolute; top:-80px; right:-80px;
    width:300px; height:300px;
    background:radial-gradient(circle, rgba(184,146,58,0.1) 0%, transparent 70%);
}
.hero-label { letter-spacing:3px; color:var(--gold2); font-weight:600; font-size:10px; margin-bottom:10px; text-transform:uppercase; }
.hero-title { font-family:'Playfair Display',serif; font-size:42px; margin:0 0 24px 0; color:#F7F4EE; line-height:1.2; }
.hero-title em { font-style:italic; color:var(--gold2); }
.hero-stats { display:flex; gap:48px; }
.hero-stat-val { font-size:28px; font-family:'JetBrains Mono',monospace; color:#F7F4EE; font-weight:500; }
.hero-stat-label { font-size:9px; opacity:0.4; letter-spacing:1.5px; text-transform:uppercase; margin-top:3px; }

/* ── MOVER CARD — wraps both top + bottom ── */
.mover-wrap {
    margin-bottom: 10px;
    border-radius: 12px;
    transition: box-shadow 0.18s, transform 0.18s;
    cursor: default;
}
.mover-wrap:hover {
    box-shadow: 0 4px 18px rgba(0,0,0,0.12);
    transform: translateY(-2px);
}
.mover-top {
    border-radius: 12px 12px 0 0;
    padding: 16px 20px 12px;
    border-bottom: none !important;
}
.mover-bottom {
    border-radius: 0 0 12px 12px;
    padding: 8px 20px 12px;
}

/* ── SIGNAL CARD ── */
.signal-card {
    border-radius: 10px;
    padding: 12px 16px;
    margin-bottom: 8px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    transition: box-shadow 0.15s, transform 0.15s;
    cursor: default;
}
.signal-card:hover {
    box-shadow: 0 3px 14px rgba(0,0,0,0.12);
    transform: translateY(-1px);
}

/* ── STAT CARDS ── */
.stat-card {
    background:var(--card); border:1px solid var(--border);
    border-left:3px solid var(--gold); border-radius:10px; padding:16px 20px;
}
.stat-val { font-family:'JetBrains Mono',monospace; font-size:20px; font-weight:500; color:var(--text); }
.stat-lbl { font-size:10px; color:var(--subtext); text-transform:uppercase; letter-spacing:0.1em; margin-top:4px; }

/* ── LEADER ROW ── */
.leader-row {
    display:flex; justify-content:space-between; align-items:center;
    padding:12px 18px; background:var(--card); border:1px solid var(--border);
    border-radius:10px; margin-bottom:8px; font-size:13px;
    transition:box-shadow 0.15s, transform 0.15s; cursor:default;
}
.leader-row:hover { box-shadow:0 3px 14px rgba(0,0,0,0.12); transform:translateY(-1px); }

/* ── BADGES ── */
.badge { display:inline-flex;align-items:center;padding:2px 9px;border-radius:20px;font-size:10px;font-weight:700;letter-spacing:0.04em;text-transform:uppercase; }
.badge-conviction { background:#FEE2E2;color:#9B2335; }
.badge-building   { background:#FEF3C7;color:#92400E; }
.badge-watching   { background:#DBEAFE;color:#1E40AF; }
.badge-neutral    { background:#F3F4F6;color:#6B7280; }
.badge-intraday   { background:#F0FDF4;color:#166534; }
.badge-grinder    { background:#FEF3C7;color:#78350F; }
.badge-coiling    { background:#EDE9FE;color:#5B21B6; }
.badge-pullback   { background:#FEE2E2;color:#7F1D1D; }
.badge-cooling    { background:#F3F4F6;color:#374151; }

.sec-hdr { display:flex;align-items:baseline;gap:12px;margin-bottom:16px; }
.sec-hdr-title { font-family:'Playfair Display',serif;font-size:18px;font-weight:600;color:var(--text); }
.sec-hdr-line  { flex:1;height:1px;background:var(--border); }
.sec-hdr-meta  { font-size:11px;color:var(--subtext); }

div[data-testid="stSelectbox"] label,
div[data-testid="stSlider"] label { font-size:11px !important; color:var(--subtext) !important; text-transform:uppercase; letter-spacing:0.08em; font-weight:500; }
div[data-testid="stSelectbox"] > div > div { border:1px solid var(--border) !important; border-radius:8px !important; background:var(--card) !important; }
div[data-testid="stSelectbox"] > div > div > div { color:var(--text) !important; font-size:13px !important; font-weight:500 !important; }

div[data-testid="stRadio"] label p { color:var(--text) !important; font-weight:600 !important; font-size:12px !important; }
div[data-testid="stRadio"] > div > label { background:var(--card) !important; border:1px solid var(--border) !important; border-radius:8px !important; padding:6px 16px !important; }
div[data-testid="stRadio"] > div > label:has(input:checked) { border-color:var(--gold) !important; }

.page-section { background:var(--card);border:1px solid var(--border);border-radius:12px;padding:32px;margin-bottom:20px; }
.mission-block { background:var(--navy);border-radius:12px;padding:32px;margin-bottom:20px;color:white; }
.mission-quote { font-family:'Playfair Display',serif;font-size:18px;font-style:italic;line-height:1.65;color:#F7F4EE;border-left:3px solid var(--gold2);padding-left:18px; }
.tech-pill { display:inline-block;background:var(--bg2);border:1px solid var(--border);border-radius:20px;padding:3px 10px;font-size:10px;font-weight:500;margin:3px;color:var(--text); }
.step-card {
    background:linear-gradient(145deg, var(--card) 0%, rgba(184,146,58,0.07) 100%);
    border:none;
    border-top:3px solid var(--gold);
    border-radius:12px;
    padding:22px 18px;
    height:100%;
    box-shadow:0 2px 12px rgba(0,0,0,0.12);
    transition:box-shadow 0.2s ease;
}
.step-card:hover { box-shadow:0 4px 20px rgba(184,146,58,0.2); }
.step-num { font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--gold);font-weight:700;letter-spacing:0.18em;text-transform:uppercase;margin-bottom:10px; }
.step-title { font-family:'Playfair Display',serif;font-size:15px;font-weight:600;color:var(--text);margin-bottom:8px; }
.step-desc { font-size:12px;color:var(--subtext);line-height:1.75; }
.contact-card { background:var(--card);border:1px solid var(--border);border-radius:10px;padding:22px; }

.footer-text { text-align:center;color:var(--subtext);font-size:10px;margin-top:48px;padding-top:20px;border-top:1px solid var(--border);font-family:'JetBrains Mono',monospace;letter-spacing:0.05em; }
"""

st.markdown(f"<style>{DARK_CSS if dm else LIGHT_CSS}{SHARED_CSS}</style>", unsafe_allow_html=True)

# ── SUPABASE ──────────────────────────────────────────────────────────────────
@st.cache_resource
def init_supabase():
    url = os.getenv("SUPABASE_URL"); key = os.getenv("SUPABASE_KEY")
    if not url or not key: return None
    return create_client(url, key)

supabase = init_supabase()

@st.cache_data(ttl=30)
def fetch_market_data():
    if not supabase: return pd.DataFrame(), pd.DataFrame()
    try:
        rs = supabase.table("coin_state").select("*").order("change_24hr", desc=True).execute()
        cutoff = (datetime.utcnow() - timedelta(hours=1)).isoformat()
        rg = supabase.table("signals").select("*").gte("triggered_at", cutoff).order("triggered_at", desc=True).execute()
        return (pd.DataFrame(rs.data) if rs.data else pd.DataFrame(),
                pd.DataFrame(rg.data) if rg.data else pd.DataFrame())
    except Exception as e:
        st.error(f"Supabase error: {e}"); return pd.DataFrame(), pd.DataFrame()

@st.cache_data(ttl=30)
def fetch_signals_filtered(minutes=1440):
    if not supabase: return pd.DataFrame()
    try:
        cutoff = (datetime.utcnow() - timedelta(minutes=minutes)).isoformat()
        res = supabase.table("signals").select("*").gte("triggered_at", cutoff).order("triggered_at", desc=True).execute()
        return pd.DataFrame(res.data) if res.data else pd.DataFrame()
    except: return pd.DataFrame()

@st.cache_data(ttl=30)
def fetch_coin_signals(pid):
    if not supabase: return pd.DataFrame()
    try:
        res = supabase.table("signals").select("*").eq("product_id", pid).order("triggered_at", desc=True).limit(50).execute()
        return pd.DataFrame(res.data) if res.data else pd.DataFrame()
    except: return pd.DataFrame()

@st.cache_data(ttl=60)
def fetch_l2_count_24hr():
    if not supabase: return 0
    try:
        cutoff = (datetime.utcnow() - timedelta(hours=24)).isoformat()
        res = supabase.table("signals").select("product_id").eq("level", 2).gte("triggered_at", cutoff).execute()
        if not res.data:
            return 0
        df = pd.DataFrame(res.data)
        return int(df["product_id"].nunique())
    except:
        return 0

@st.cache_data(ttl=60)
def fetch_open_positions():
    if not supabase: return 0, []
    try:
        res = supabase.table("coin_state").select(
            "product_id, l2_price, current_price, tp1_hit"
        ).eq("l2_fired", True)\
         .eq("position_closed", False)\
         .eq("sl_hit", False)\
         .eq("tp2_hit", False)\
         .eq("time_stop_hit", False)\
         .execute()
        if not res.data:
            return 0, []
        coins = [r["product_id"].replace("-USD", "") for r in res.data]
        return len(coins), coins
    except:
        return 0, []

@st.cache_data(ttl=300)
def fetch_tp1_rate():
    if not supabase: return 0, 0, 0
    try:
        cutoff = "2026-06-15"
        res = supabase.table("coin_state").select(
            "tp1_hit, l2_fired, l2_price"
        ).eq("l2_fired", True)\
         .gt("l2_price", 0)\
         .gte("l2_fired_at", cutoff)\
         .execute()
        if not res.data:
            return 0, 0, 0
        df = pd.DataFrame(res.data)
        total    = len(df)
        tp1_hits = int(df["tp1_hit"].sum())
        rate     = round((tp1_hits / total * 100), 1) if total > 0 else 0
        return rate, tp1_hits, total
    except:
        return 0, 0, 0

@st.cache_data(ttl=60)
def fetch_last_scan():
    if not supabase:
        return "—", "—"
    try:
        res = supabase.table("coin_state").select("updated_at").order("updated_at", desc=True).limit(1).execute()
        if not res.data:
            return "—", "—"
        last = datetime.fromisoformat(str(res.data[0]["updated_at"]).replace("Z", "+00:00"))
        minutes_ago = int((datetime.now(timezone.utc) - last).total_seconds() / 60)
        if minutes_ago < 1:
            time_str = "just now"
        elif minutes_ago == 1:
            time_str = "1 min ago"
        else:
            time_str = f"{minutes_ago} min ago"
        return time_str, last.astimezone(CDMX).strftime("%I:%M %p")
    except:
        return "—", "—"

@st.cache_data(ttl=300)
def fetch_fng():
    try:
        r = requests.get("https://api.alternative.me/fng/?limit=1", timeout=5)
        d = r.json()["data"][0]
        return int(d["value"]), d["value_classification"]
    except: return None, None

@st.cache_data(ttl=60)
def fetch_btc():
    try:
        spot = requests.get("https://api.coinbase.com/v2/prices/BTC-USD/spot", timeout=5)
        price = float(spot.json()["data"]["amount"])
        
        # 24hr change via Coinbase
        stats = requests.get("https://api.exchange.coinbase.com/products/BTC-USD/stats", timeout=5)
        s = stats.json()
        open_24 = float(s["open"])
        change_pct = ((price - open_24) / open_24) * 100

        # sparkline: last 24 candles (1hr each)
        candles = requests.get(
            "https://api.exchange.coinbase.com/products/BTC-USD/candles?granularity=3600&limit=24",
            timeout=5
        )
        closes = [c[4] for c in reversed(candles.json())]
        return price, change_pct, closes
    except: return None, None, []

@st.cache_data(ttl=300)
def fetch_hall_of_fame():
    if not supabase: return pd.DataFrame()
    try:
        res = supabase.table("hall_of_fame").select(
            "product_id, exit_type, exit_gain, peak_gain, "
            "accel_count, rsi, rs_vs_btc, l2_type, l2_fired_at"
        ).order("l2_fired_at", desc=True).execute()
        return pd.DataFrame(res.data) if res.data else pd.DataFrame()
    except: return pd.DataFrame()

# ── HELPERS ───────────────────────────────────────────────────────────────────
def badge(cls, l2_type=""):
    c = str(cls or "")
    t = str(l2_type or "")
    if "HIGH CONVICTION" in c: return '<span class="badge badge-conviction">● HIGH CONVICTION</span>'
    if "BUILDING" in c and t == "volume": return '<span class="badge badge-conviction">● L2 VOLUME</span>'
    if "BUILDING" in c and t == "accel":  return '<span class="badge badge-building">● L2 ACCEL</span>'
    if "BUILDING"        in c: return '<span class="badge badge-building">● BUILDING</span>'
    if "WATCHING"        in c: return '<span class="badge badge-watching">● WATCHING</span>'
    if "INTRADAY"        in c: return '<span class="badge badge-intraday">● INTRADAY MOVER</span>'
    if "SLOW GRINDER"    in c: return '<span class="badge badge-grinder">● SLOW GRINDER</span>'
    if "COILING"         in c: return '<span class="badge badge-coiling">● COILING</span>'
    if "PULLBACK"        in c: return '<span class="badge badge-pullback">● PULLBACK</span>'
    if "COOLING"         in c: return '<span class="badge badge-cooling">● COOLING</span>'
    return '<span class="badge badge-neutral">● NEUTRAL</span>'

def signal_tier(row):
    l2t   = str(row.get("l2_type", "") or "")
    accel = int(row.get("accel_count", 0) or 0)
    l2    = bool(row.get("l2_fired", False))
    if l2 and l2t == "volume" and accel >= 1:
        return "HIGH CONVICTION", c_green, chip_green_bg
    elif l2 and l2t == "volume":
        return "CONFIRMED", c_amber, chip_amber_bg
    elif l2 and l2t in ("dynamic", "accel"):
        return "EARLY SIGNAL", c_blue_bright, chip_blue_bg
    elif l2:
        return "CONFIRMED", c_amber, chip_amber_bg
    else:
        return "WATCHING", c_grey_mid, chip_grey_bg

def fmt_time(ts):
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z","+00:00"))
        return dt.astimezone(CDMX).strftime("%I:%M %p")
    except: return ""

def safe_val(val, fmt=None, fallback="—"):
    try:
        if val is None: return fallback
        f = float(val)
        if math.isnan(f) or math.isinf(f): return fallback
        if fmt: return fmt.format(f)
        return f
    except: return fallback

def safe_price(val, d=None):
    try:
        v = float(val or 0)
        if math.isnan(v) or math.isinf(v): return "—"
        if v == 0: return "—"
        if v < 0.0001:  return f"${v:.8f}"
        if v < 0.001:   return f"${v:.6f}"
        if v < 0.1:     return f"${v:.4f}"
        if v < 1:       return f"${v:.4f}"
        if v < 100:     return f"${v:.2f}"
        return f"${v:,.2f}"
    except: return "—"



def border_color(cls):
    c = str(cls or "")
    if "HIGH" in c:     return c_red
    if "BUILD" in c:    return c_amber
    if "WATCH" in c:    return c_blue_bright
    if "INTRADAY" in c: return chip_green_text
    return c_border

# ── DATA ──────────────────────────────────────────────────────────────────────
states_df, signals_df = fetch_market_data()
total_sig = len(signals_df) if not signals_df.empty else 0
tp1_rate, tp1_hits_recent, tp1_total_recent = fetch_tp1_rate()
tp1_rate_color = "#1A7A4A" if tp1_rate >= 10 else "#B8923A" if tp1_rate >= 5 else "#9B2335"
l2_count  = len(signals_df[signals_df["level"]==2]) if not signals_df.empty else 0
high_conv = len(states_df[states_df["classification"].str.contains("HIGH CONVICTION",na=False)]) if not states_df.empty else 0
gainers_n = len(states_df[states_df["change_24hr"]>=15]) if not states_df.empty else 0

# ── INLINE THEME COLORS ───────────────────────────────────────────────────────
c_text   = "#e8e8f0" if dm else "#0E1B2E"
c_sub    = "#888888" if dm else "#6B7280"
c_card   = "#12121a" if dm else "white"
c_border = "#1e1e2e" if dm else "#DDD8CE"
c_bg2    = "#1e1e2e" if dm else "#EDE9DF"
c_green  = "#00ff88" if dm else "#1A7A4A"
c_red    = "#ff4444" if dm else "#9B2335"
c_gold   = "#D4A853"

# ── Accent colors — single source of truth ───────────────────────────
c_amber        = "#B8923A"   # warning / extended / amber states
c_amber_bright = "#FF8F00"   # confirmed tier / moderate positive
c_blue         = "#2979FF"   # HH/HL / early signal / blue tier
c_blue_bright  = "#42A5F5"   # early signal highlight / watch tier
c_purple       = "#7C3AED"   # coiling
c_grey_mid     = "#9E9E9E"   # watching tier / neutral

# ── Status chip colors ────────────────────────────────────────────────
chip_green_bg   = "#F0FDF4"
chip_green_text = "#166534"
chip_amber_bg   = "#FEF3C7"
chip_amber_text = "#92400E"
chip_red_bg     = "#FEE2E2"
chip_red_text   = "#9B2335"
chip_grey_bg    = "#F3F4F6"
chip_grey_text  = "#6B7280"
chip_blue_bg    = "#DBEAFE"
chip_blue_text  = "#1E40AF"

shadow = "rgba(0,0,0,0.4)" if dm else "rgba(14,27,46,0.1)"

# ── NAV ───────────────────────────────────────────────────────────────────────
n1,n2,n3,n4,n5,n6 = st.columns([3,1,1,1.2,1,0.6])
with n1:
    st.markdown("""
    <style>
    @keyframes slideFromRight {
        from { opacity: 0; transform: translateX(80px); }
        to   { opacity: 1; transform: translateX(0); }
    }
    @keyframes gold-shift {
        0%   { background-position: 0% 50%; }
        50%  { background-position: 100% 50%; }
        100% { background-position: 0% 50%; }
    }
    .momentum-text {
        background: linear-gradient(90deg, #B8923A, #F5D78E, #D4A853, #F5D78E, #B8923A);
        background-size: 300% 300%;
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        animation: gold-shift 4s ease infinite;
        font-family: "Playfair Display", serif;
        font-size: 1.5rem;
        font-weight: 700;
        margin: 0;
        padding: 6px 0;
        display: inline-block;
    }
    .nav-sub-t  { display:inline-block; animation: slideFromRight 0.6s ease forwards; }
    .nav-sub-s  { display:inline-block; color:#D4A853; opacity:0; animation: slideFromRight 0.8s ease 0.4s forwards; }
    .nav-sub-m  { display:inline-block; opacity:0; animation: slideFromRight 0.6s ease 0.2s forwards; }
    .nav-sub-p  { display:inline-block; color:#1A7A4A; opacity:0; animation: slideFromRight 0.8s ease 0.7s forwards; }
    .nav-sub-end{ display:inline-block; opacity:0; animation: slideFromRight 0.6s ease 0.5s forwards; }
    </style>
    <span class="momentum-text">MOMENTUM<span style="-webkit-text-fill-color:#D4A853">.</span></span>
    <p style='font-family:"Playfair Display",serif;color:#888;font-size:14px;margin:0;padding:0 0 4px 0;'>
        <span class="nav-sub-t">Track the</span><span class="nav-sub-s">&nbsp;surge</span><span class="nav-sub-m">. Catch the</span><span class="nav-sub-p">&nbsp;pump</span><span class="nav-sub-end">.</span>
    </p>
    """, unsafe_allow_html=True)
cur = st.session_state.page
if n2.button("Dashboard",    use_container_width=True, key="nav_active" if cur=="Dashboard"    else "nav_d"): st.session_state.page="Dashboard"; st.query_params["page"]="Dashboard"; st.cache_data.clear(); st.rerun()
if n3.button("About",        use_container_width=True, key="nav_active" if cur=="About"        else "nav_a"): st.session_state.page="About";     st.query_params["page"]="About";     st.rerun()
if n4.button("How It Works", use_container_width=True, key="nav_active" if cur=="HowItWorks"   else "nav_h"): st.session_state.page="HowItWorks"; st.query_params["page"]="HowItWorks"; st.rerun()
if n5.button("Contact",      use_container_width=True, key="nav_active" if cur=="Contact"      else "nav_c"): st.session_state.page="Contact";    st.query_params["page"]="Contact";    st.rerun()
with n6:
    if st.button("Light" if dm else "Dark", use_container_width=True, key="nav_theme"):
        st.session_state.dark_mode = not dm; st.rerun()

st.markdown("<hr style='margin:0.4rem 0 1.6rem;opacity:0.15'>", unsafe_allow_html=True)

# ════════════════════════════════════════════════════════════════════════════
# DASHBOARD
# ════════════════════════════════════════════════════════════════════════════
def make_sparkline(prices, color, bg=False):
    if not prices or len(prices) < 2: return ""
    mn, mx = min(prices), max(prices)
    rng = mx - mn if mx != mn else 1
    w, h = (400, 80) if bg else (70, 22)
    pts = []
    for i, p in enumerate(prices):
        x = i / (len(prices)-1) * w
        y = h - ((p - mn) / rng * (h * 0.7)) - (h * 0.15)
        pts.append(f"{x:.1f},{y:.1f}")
    path = " ".join(pts)
    style = 'position:absolute;top:0;left:0;width:100%;height:100%;opacity:0.28;pointer-events:none;' if bg else ''
    return f'''<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg" style="{style}">
      <polyline points="{path}" fill="none" stroke="{color}" stroke-width="{'2.5' if bg else '1.5'}" stroke-linejoin="round" stroke-linecap="round"/>
    </svg>'''

if st.session_state.page == "Dashboard":

    btc_price, btc_change, btc_sparkline = fetch_btc()
    btc_display = f"${btc_price:,.0f}" if btc_price else "—"
    btc_change_color = c_green if btc_change and btc_change >= 0 else c_red
    btc_change_display = f"{btc_change:+.2f}%" if btc_change is not None else "—"
    btc_spark_svg = make_sparkline(btc_sparkline, btc_change_color)
    btc_spark_bg  = make_sparkline(btc_sparkline, btc_change_color, bg=True)

    fng_val, fng_label = fetch_fng()
    fng_color = c_green if fng_val and fng_val>=60 else c_gold if fng_val and fng_val>=40 else c_red
    fng_display = str(fng_val) if fng_val else "—"
    fng_lbl_display = fng_label if fng_label else "unavailable"

    l2s_24hr = fetch_l2_count_24hr()
    l2s_color    = c_green if l2s_24hr >= 30 else c_amber if l2s_24hr >= 15 else c_red
    l2s_activity = "active market" if l2s_24hr >= 30 else "moderate" if l2s_24hr >= 15 else "quiet day"

    open_count, open_coins = fetch_open_positions()
    open_color     = c_green if open_count >= 3 else c_amber if open_count >= 1 else c_red
    open_coins_str = " · ".join(open_coins) if open_coins else "none"

    last_scan_ago, last_scan_time = fetch_last_scan()
    last_scan_color = c_green if "min" in last_scan_ago and int(last_scan_ago.split()[0]) <= 7 else c_amber if last_scan_ago != "—" else c_red

    # Best open position gain right now
    best_open_gain = 0
    best_open_coin = "—"
    if not states_df.empty:
        open_pos = states_df[
            states_df["l2_fired"] &
            ~states_df["position_closed"] &
            ~states_df["sl_hit"] &
            ~states_df["tp2_hit"] &
            ~states_df["time_stop_hit"] &
            (states_df["l2_price"] > 0) &
            (states_df["current_price"] > 0)
        ].copy()
        if not open_pos.empty:
            open_pos["open_gain"] = ((open_pos["current_price"] - open_pos["l2_price"]) / open_pos["l2_price"] * 100)
            best_open_row = open_pos.loc[open_pos["open_gain"].idxmax()]
            best_open_gain = round(float(best_open_row["open_gain"]), 1)
            best_open_coin = str(best_open_row["product_id"]).replace("-USD", "")

    best_open_color = c_green if best_open_gain > 0 else c_red if best_open_gain < 0 else c_sub
    best_open_display = f"{best_open_gain:+.1f}%" if best_open_coin != "—" else "—"
    _has_open = best_open_coin != "—"
    _hero_grad   = f"linear-gradient(145deg, {c_card} 0%, {best_open_color}18 100%)" if _has_open else f"linear-gradient(145deg, {c_card} 0%, rgba(212,168,83,0.07) 100%)"
    _hero_border = f"1px solid {best_open_color}40" if _has_open else "none"
    _hero_shadow = f"0 0 18px 4px {best_open_color}2E" if _has_open else "0 2px 12px rgba(0,0,0,0.12)"
    _hero_anim   = "bestOpenGlow 2s ease-in-out infinite" if _has_open else "none"

    # Card 1 — Avg trail exit
    avg_trail_exit   = 0
    worst_trail_exit = 0
    trail_exit_count = 0
    if not states_df.empty:
        trail_df = states_df[
            states_df["tp2_hit"] &
            (states_df["trailing_high"] > 0) &
            (states_df["l2_price"] > 0)
        ].copy()
        if not trail_df.empty:
            trail_df["trail_pct"] = ((trail_df["trailing_high"] - trail_df["l2_price"]) / trail_df["l2_price"] * 100)
            avg_trail_exit   = round(float(trail_df["trail_pct"].mean()), 1)
            worst_trail_exit = round(float(trail_df["trail_pct"].min()), 1)
            trail_exit_count = len(trail_df)

    # Card 2 — Profitable exit rate (reuses trail_df from Card 1)
    profitable_exit_rate = 0
    if trail_exit_count > 0 and not trail_df.empty:
        profitable_count     = len(trail_df[trail_df["trail_pct"] > 0])
        profitable_exit_rate = round((profitable_count / trail_exit_count) * 100)

    # Card 3 — Avg peak high conviction (accel_count >= 1)
    avg_peak_high_conv = 0
    high_conv_count    = 0
    if not states_df.empty:
        hc_df = states_df[
            states_df["l2_fired"] &
            (states_df["accel_count"] >= 1) &
            (states_df["l2_price"] > 0) &
            (states_df["peak_price"] > 0)
        ].copy()
        if not hc_df.empty:
            hc_df["peak_pct"]  = ((hc_df["peak_price"] - hc_df["l2_price"]) / hc_df["l2_price"] * 100)
            avg_peak_high_conv = round(float(hc_df["peak_pct"].mean()), 1)
            high_conv_count    = len(hc_df)

    # Card 4 — Avg peak detected across all L2s
    avg_peak_all  = 0
    total_l2s_all = 0
    if not states_df.empty:
        all_df = states_df[
            states_df["l2_fired"] &
            (states_df["l2_price"] > 0) &
            (states_df["peak_price"] > 0)
        ].copy()
        if not all_df.empty:
            all_df["peak_pct"] = ((all_df["peak_price"] - all_df["l2_price"]) / all_df["l2_price"] * 100)
            avg_peak_all  = round(float(all_df["peak_pct"].mean()), 1)
            total_l2s_all = len(all_df)

    st.markdown(f"""
<style>
@keyframes blink {{
    0%, 100% {{ opacity: 1; }}
    50%       {{ opacity: 0; }}
}}
.live-dot {{
    display: inline-block;
    width: 7px; height: 7px;
    background: #ff4444;
    border-radius: 50%;
    margin-right: 5px;
    animation: blink 1.2s ease-in-out infinite;
}}
.live-text {{
    color: #ff4444;
    font-weight: 700;
    animation: blink 1.2s ease-in-out infinite;
}}
.metric-card {{
    background: linear-gradient(145deg, {c_card} 0%, rgba(26,122,74,0.07) 100%);
    border: none;
    box-shadow: 0 2px 12px rgba(0,0,0,0.12);
    border-radius: 12px;
    padding: 18px 22px;
    flex: 1;
    min-width: 0;
    text-align: center;
}}
.metric-card-val {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 33px;
    font-weight: 600;
    color: {c_text};
    margin-bottom: 4px;
}}
.metric-card-lbl {{
    font-size: 12px;
    color: {c_text};
    text-transform: uppercase;
    letter-spacing: 0.14em;
}}
.metric-card-sub {{
    font-size: 12px;
    margin-top: 4px;
}}
.metric-card-sm {{
    background: linear-gradient(145deg, {c_card} 0%, rgba(212,168,83,0.07) 100%);
    border: none;
    box-shadow: 0 2px 12px rgba(0,0,0,0.12);
    border-radius: 10px;
    padding: 12px 18px;
    text-align: center;
    min-width: 0;
}}
.metric-card-sm .metric-card-val {{
    font-size: 22px;
}}
.metric-card-sm .metric-card-lbl {{
    font-size: 10px;
}}
.metric-card-sm .metric-card-sub {{
    font-size: 10px;
}}
@keyframes bestOpenGlow {{
    0%, 100% {{ box-shadow: {_hero_shadow}; }}
    50%       {{ box-shadow: 0 0 32px 8px {best_open_color}47; }}
}}
@keyframes livePulse {{
    0%, 100% {{ opacity:1; transform:scale(1); }}
    50%       {{ opacity:0.25; transform:scale(0.55); }}
}}
</style>
<div style="margin-bottom:8px;">
  <div class="hero-label" style="margin-bottom:12px;">
    Coinbase Signal Tracker &nbsp;—&nbsp;
    <span class="live-dot"></span><span class="live-text">LIVE</span>
  </div>
  <div style="display:flex; justify-content:space-between; align-items:stretch; margin-bottom:12px;">
    <div style="display:flex; gap:10px;">
      <div class="metric-card-sm" style="width:160px;">
        <div class="metric-card-lbl" style="font-size:10px;">L2s Today</div>
        <div class="metric-card-val" style="font-size:22px; margin-top:2px; color:{l2s_color};">{l2s_24hr}</div>
        <div class="metric-card-sub" style="color:{l2s_color}; font-size:10px;">{l2s_activity}</div>
      </div>
      <div class="metric-card-sm" style="width:160px;">
        <div class="metric-card-lbl" style="font-size:10px;">Open Positions</div>
        <div class="metric-card-val" style="font-size:22px; margin-top:2px; color:{open_color};">{open_count}</div>
        <div class="metric-card-sub" style="color:{open_color}; font-size:10px;">{open_coins_str}</div>
      </div>
      <div class="metric-card-sm" style="width:160px;">
        <div class="metric-card-lbl" style="font-size:10px;">TP1 Success Rate</div>
        <div class="metric-card-val" style="font-size:22px; margin-top:2px; color:{tp1_rate_color};">{tp1_rate}%</div>
        <div class="metric-card-sub" style="color:{tp1_rate_color}; font-size:10px;">{tp1_hits_recent} exits · last 10 days</div>
      </div>
      <div class="metric-card-sm" style="width:160px;">
        <div class="metric-card-lbl" style="font-size:10px;">Last Scan</div>
        <div class="metric-card-val" style="font-size:20px; margin-top:2px; color:{last_scan_color};">{last_scan_ago}</div>
        <div class="metric-card-sub" style="font-size:10px;">{last_scan_time} · 7 min cycle</div>
      </div>
    </div>
    <div style="width:200px; background:{_hero_grad}; border:{_hero_border};
                border-radius:12px; padding:14px 20px; text-align:center; position:relative;
                box-shadow:{_hero_shadow}; animation:{_hero_anim}; align-self:stretch;
                clip-path:inset(-100px -100px 0px -100px);">
      <div style="position:absolute; top:9px; right:11px; display:flex; align-items:center; gap:4px;">
        <div style="width:6px; height:6px; border-radius:50%; background:{best_open_color};
                    animation:livePulse 1.4s ease-in-out infinite;"></div>
        <span style="font-family:'JetBrains Mono',monospace; font-size:8px; color:{best_open_color};
                     letter-spacing:0.12em; font-weight:700;">LIVE</span>
      </div>
      <div style="font-size:10px; color:{c_text}; text-transform:uppercase; letter-spacing:0.14em;">Best Open</div>
      <div style="font-family:'JetBrains Mono',monospace; font-size:30px; font-weight:700;
                  color:{best_open_color}; margin-top:4px; line-height:1;">{best_open_display}</div>
      <div style="font-size:12px; color:{best_open_color}; font-weight:600; margin-top:6px;
                  letter-spacing:0.06em;">{best_open_coin}</div>
    </div>
    <div style="display:flex; gap:10px;">
      <div class="metric-card-sm" style="width:160px; position:relative; overflow:hidden;">
        {btc_spark_bg}
        <div style="position:relative; z-index:1;">
          <div class="metric-card-lbl" style="font-size:10px;">BTC Price</div>
          <div class="metric-card-val" style="font-size:22px; margin-top:2px;">{btc_display}</div>
          <div class="metric-card-sub" style="color:{btc_change_color}; font-weight:600; font-size:10px;">{btc_change_display} 24hr</div>
        </div>
      </div>
      <div class="metric-card-sm" style="width:160px;">
        <div class="metric-card-lbl" style="font-size:10px;">Fear &amp; Greed</div>
        <div class="metric-card-val" style="font-size:22px; margin-top:2px; color:{fng_color};">{fng_display}</div>
        <div class="metric-card-sub" style="color:{fng_color}; font-size:10px;">{fng_lbl_display}</div>
      </div>
    </div>
  </div>
  <div style="display:flex; gap:14px; margin-bottom:20px;">
    <div class="metric-card" style="flex:1;">
      <div class="metric-card-val" style="color:#1A7A4A">+{avg_trail_exit}%</div>
      <div class="metric-card-lbl">Avg Trail Exit</div>
      <div class="metric-card-sub">{trail_exit_count} fully closed trades · since May 24</div>
    </div>
    <div class="metric-card" style="flex:1;">
      <div class="metric-card-val" style="color:#1A7A4A">{int(profitable_exit_rate)}%</div>
      <div class="metric-card-lbl">Profitable Exits</div>
      <div class="metric-card-sub">worst exit still +{worst_trail_exit}% · {trail_exit_count} trades</div>
    </div>
    <div class="metric-card" style="flex:1;">
      <div class="metric-card-val" style="color:#1A7A4A">+{avg_peak_high_conv}%</div>
      <div class="metric-card-lbl">Avg Peak · High Conviction</div>
      <div class="metric-card-sub">{high_conv_count} accel signals · since May 24</div>
    </div>
    <div class="metric-card" style="flex:1;">
      <div class="metric-card-val" style="color:#1A7A4A">+{avg_peak_all}%</div>
      <div class="metric-card-lbl">Avg Peak Detected</div>
      <div class="metric-card-sub">{total_l2s_all} signals · since May 24</div>
    </div>
  </div>
</div>
""", unsafe_allow_html=True)

    tab_m, tab_f, tab_d, tab_l, tab_h = st.tabs(["Active Movers","Signal Feed","Coin Detail","Leaderboard","Hall of Fame"])

    # ── ACTIVE MOVERS ──────────────────────────────────────────────────────────
    with tab_m:
        if states_df.empty:
            st.info("Waiting for market data.")
        else:
            active = states_df[states_df["change_24hr"].notna()].copy()
            active = active[
                (active["change_24hr"] >= 5) |
                (
                    active["l2_fired"] &
                    ~active["position_closed"] &
                    ~active["sl_hit"] &
                    ~active["time_stop_hit"] &
                    ~active["tp2_hit"]
                )
            ].sort_values("change_24hr", ascending=False)

            st.markdown(f'<div class="sec-hdr"><span class="sec-hdr-title">Active Movers</span><div class="sec-hdr-line"></div><span class="sec-hdr-meta">{len(active)} coins · {datetime.now(timezone.utc).astimezone(CDMX).strftime("%I:%M %p")}</span></div>', unsafe_allow_html=True)

            cards_html = ""
            for _, row in active.iterrows():
                    c24      = float(row.get("change_24hr",0) or 0)
                    price    = float(row.get("current_price",0) or 0)
                    accel    = int(row.get("accel_count",0) or 0)
                    l2       = bool(row.get("l2_fired",False))
                    dump     = bool(row.get("dump_fired",False))
                    l2p      = float(row.get("l2_price") or 0)
                    peak     = float(row.get("peak_price") or 0)
                    cls      = str(row.get("classification","") or "")
                    rfl      = float(row.get("range_from_low",0) or 0)
                    tier_label, tier_color, tier_bg = signal_tier(row)
                    fire     = "+" * min(accel,4)
                    gfl2     = round((price-l2p)/l2p*100,1) if l2p>0 else 0
                    gfpk     = round((peak-l2p)/l2p*100,1) if l2p>0 else 0
                    c24c     = c_green if c24>0 else c_red
                    bdr      = tier_color
                    l2t      = str(row.get("l2_type","") or "")

                    # L2 badge string
                    if l2 and l2t == "volume":
                        l2_badge = f'<span style="background:{chip_red_bg};color:{chip_red_text};font-size:9px;font-weight:700;padding:2px 6px;border-radius:4px;letter-spacing:0.04em">L2 VOL</span>'
                        sig_trigger = f'<span style="color:{c_green};font-weight:600">Volume spike — high-conviction buy signal</span>'
                        sig_entry   = f'<span style="color:{c_sub}">L2 entry @ {safe_price(l2p,4)}</span>'
                    elif l2 and l2t == "accel":
                        l2_badge = f'<span style="background:{chip_amber_bg};color:{c_amber};font-size:9px;font-weight:700;padding:2px 6px;border-radius:4px;letter-spacing:0.04em">L2 ACCEL</span>'
                        sig_trigger = f'<span style="color:{c_gold};font-weight:600">Acceleration confirmed — momentum building</span>'
                        sig_entry   = f'<span style="color:{c_sub}">L2 entry @ {safe_price(l2p,4)}</span>'
                    elif l2:
                        l2_badge = f'<span style="background:{chip_amber_bg};color:{c_amber};font-size:9px;font-weight:700;padding:2px 6px;border-radius:4px;letter-spacing:0.04em">L2</span>'
                        sig_trigger = f'<span style="color:{c_gold};font-weight:600">L2 signal confirmed</span>'
                        sig_entry   = f'<span style="color:{c_sub}">Entry @ {safe_price(l2p,4)}</span>'
                    else:
                        l2_badge    = ""
                        sig_trigger = f'<span style="color:{c_sub}">Watching — no L2 confirmation yet</span>'
                        sig_entry   = ""

                    # Zone 2 — performance line
                    perf_line_parts = []
                    if l2 and gfl2 != 0:
                        clr = c_green if gfl2 > 0 else c_red
                        perf_line_parts.append(f'<span style="color:{clr};font-weight:600">{gfl2:+.1f}% since entry</span>')
                    if peak > 0 and l2:
                        perf_line_parts.append(f'<span style="color:{c_sub}">peak {gfpk:+.1f}% ({safe_price(peak,4)})</span>')
                    perf_line_parts.append(f'<span style="color:{c_sub}">+{rfl:.1f}% off 24hr low</span>')
                    perf_line = "&nbsp;&nbsp;·&nbsp;&nbsp;".join(perf_line_parts)

                    sig_line = f'{sig_trigger}{"&nbsp;&nbsp;·&nbsp;&nbsp;"+sig_entry if sig_entry else ""}'

                    card = (
                        f'<div style="margin-bottom:6px">'
                        f'<div style="background:linear-gradient(135deg, {c_card} 0%, {bdr}26 100%);border:1px solid {c_border};border-left:4px solid {bdr};border-radius:8px;padding:10px 16px;display:flex;gap:14px;align-items:center">'
                        f'<div style="flex:1;min-width:0">'
                        f'<div style="display:flex;align-items:center;gap:7px;margin-bottom:7px">'
                        f'<span style="font-family:\'JetBrains Mono\',monospace;font-size:13px;font-weight:700;color:{c_text}">{row["product_id"]}</span>'
                        f'{badge(cls, l2t)}'
                        f'{l2_badge}'
                        f'</div>'
                        f'<div style="display:flex;align-items:center;font-size:11px;margin-bottom:8px">'
                        f'<div style="flex:1;overflow:hidden;white-space:nowrap;text-overflow:ellipsis">{sig_line}</div>'
                        f'<div style="width:1px;background:{c_border};align-self:stretch;margin:0 12px;flex-shrink:0"></div>'
                        f'<div style="flex:1;overflow:hidden;white-space:nowrap;text-overflow:ellipsis">{perf_line}</div>'
                        f'</div>'
                        f'<span style="font-size:9px;background:{tier_bg};color:{tier_color};padding:1px 6px;border-radius:4px;font-weight:700">{tier_label}</span>'
                        f'</div>'
                        f'<div style="display:flex;flex-direction:column;align-items:flex-end;justify-content:center;flex-shrink:0;gap:3px">'
                        f'<span style="font-family:\'JetBrains Mono\',monospace;font-size:11px;color:{c_sub}">{safe_price(price)}</span>'
                        f'<span style="font-family:\'JetBrains Mono\',monospace;font-size:14px;font-weight:700;color:{c24c}">{c24:+.2f}%</span>'
                        f'</div>'
                        f'</div>'
                        f'</div>'
                    )
                    cards_html += card

            st.markdown(f"""
            <style>.movers-scroll::-webkit-scrollbar{{display:none}}</style>
            <div class="movers-scroll" style="height:620px;overflow-y:scroll;padding:24px 2px;
                -webkit-mask-image:linear-gradient(to bottom,transparent 0%,black 10%,black 90%,transparent 100%);
                mask-image:linear-gradient(to bottom,transparent 0%,black 10%,black 90%,transparent 100%);
                scrollbar-width:none;">
            {cards_html}
            </div>""", unsafe_allow_html=True)


    # ── SIGNAL FEED ────────────────────────────────────────────────────────────
    with tab_f:
        st.markdown(f'<div class="sec-hdr"><span class="sec-hdr-title">Signal Feed</span><div class="sec-hdr-line"></div></div>', unsafe_allow_html=True)

        f1,f2,f3 = st.columns(3)
        with f1: tf_f  = st.selectbox("Timeframe", ["All","5min","15min","30min","1hour","24hour"], index=0)
        with f2: dir_f = st.selectbox("Direction", ["Pump","Dump","All"], index=0)
        with f3: lv_f  = st.selectbox("Level",     ["L2 only","All","L1 only"], index=0)

        feed_df = fetch_signals_filtered(24*60)
        if not feed_df.empty:
            df = feed_df.copy()
            if tf_f  != "All": df = df[df["timeframe"]==tf_f]
            if dir_f == "Pump":
                df = df[df["price_change"] > 0]
            elif dir_f == "Dump":
                df = df[df["price_change"] < 0]
            if lv_f == "L2 only":
                df = df[df["level"].astype(str) == "2"]
            elif lv_f == "L1 only":
                df = df[df["level"].astype(str) == "1"]

            if not df.empty:
                df["triggered_at"] = pd.to_datetime(df["triggered_at"])
                df["hour_bucket"]  = df["triggered_at"].dt.floor("h")
                df = df.sort_values("volume_ratio", ascending=False)
                df = df.drop_duplicates(subset=["product_id", "hour_bucket"])
                df = df.sort_values("triggered_at", ascending=False)

            st.markdown(f'<p style="font-size:11px;color:{c_sub};margin-bottom:10px">{len(df)} signals · {df["product_id"].nunique() if not df.empty else 0} unique coins · last 24hrs</p>', unsafe_allow_html=True)

            # Merge current price from coin_state for gain since entry calculation
            price_map = {}
            if not states_df.empty:
                _cols = ["product_id","current_price","position_closed","sl_hit",
                         "time_stop_hit","tp1_hit","rsi","macd_bullish","accel_count"]
                _sub = states_df[[c for c in _cols if c in states_df.columns]].copy()
                price_map = _sub.set_index("product_id").to_dict("index")

            feed_html = ""
            shown = 0
            for _, row in df.iterrows():
                if shown >= 50:
                    break

                chg  = float(row.get("price_change", 0) or 0)
                vol  = float(row.get("volume_ratio", 0) or 0)
                c24  = float(row.get("change_24hr", 0) or 0)
                pr   = float(row.get("price", 0) or 0)
                lv   = int(row.get("level", 1) or 1)
                l2t  = str(row.get("l2_type", "") or "")
                pid  = row.get("product_id", "")
                ts   = fmt_time(row.get("triggered_at", ""))
                tf   = row.get("timeframe", "")
                cc   = c_green if chg > 0 else c_red
                c24c = c_green if c24 > 0 else c_red

                if vol == 0:
                    continue

                cs        = price_map.get(pid, {})
                current   = float(cs.get("current_price") or 0)
                is_closed = cs.get("position_closed") or cs.get("sl_hit") or cs.get("time_stop_hit")
                tp1_hit   = cs.get("tp1_hit")
                rsi       = cs.get("rsi")
                macd      = cs.get("macd_bullish")
                accel     = int(cs.get("accel_count") or 0)

                if cs.get("sl_hit"):
                    status_str = f'<span style="font-size:9px;background:{chip_red_bg};color:{chip_red_text};padding:1px 5px;border-radius:3px;font-weight:700">STOPPED</span>'
                elif cs.get("tp1_hit") and cs.get("position_closed"):
                    status_str = f'<span style="font-size:9px;background:{chip_green_bg};color:{chip_green_text};padding:1px 5px;border-radius:3px;font-weight:700">EXITED</span>'
                elif cs.get("tp1_hit"):
                    status_str = f'<span style="font-size:9px;background:{chip_amber_bg};color:{chip_amber_text};padding:1px 5px;border-radius:3px;font-weight:700">TP1 HIT</span>'
                elif cs.get("time_stop_hit"):
                    status_str = f'<span style="font-size:9px;background:{chip_grey_bg};color:{chip_grey_text};padding:1px 5px;border-radius:3px;font-weight:700">TIME STOP</span>'
                else:
                    status_str = f'<span style="font-size:9px;background:{chip_green_bg};color:{chip_green_text};padding:1px 5px;border-radius:3px;font-weight:700">OPEN</span>'

                since_entry     = ((current - pr) / pr * 100) if pr > 0 and current > 0 else None
                since_entry_str = ""
                since_entry_col = c_sub
                if since_entry is not None:
                    since_entry_col = c_green if since_entry >= 0 else c_red
                    since_entry_str = f'{since_entry:+.1f}% since entry'

                if lv == 2 and l2t == "volume":
                    lbg, lco, lbl = chip_red_bg, chip_red_text, "L2 VOL"
                elif lv == 2 and l2t == "dynamic":
                    lbg, lco, lbl = chip_amber_bg, c_amber, "EARLY L2"
                elif lv == 2 and l2t == "accel":
                    lbg, lco, lbl = chip_amber_bg, c_amber, "L2 ACCEL"
                else:
                    lbg, lco, lbl = chip_grey_bg, chip_grey_text, "L1"

                if lv == 2 and l2t == "volume" and accel >= 1:
                    tier, tier_color, tier_bg = "HIGH CONVICTION", c_green, chip_green_bg
                elif lv == 2 and l2t == "volume" and vol >= 3.0:
                    tier, tier_color, tier_bg = "CONFIRMED", c_amber, chip_amber_bg
                elif lv == 2 and l2t == "volume":
                    tier, tier_color, tier_bg = "CONFIRMED", c_amber, chip_amber_bg
                elif lv == 2:
                    tier, tier_color, tier_bg = "EARLY SIGNAL", c_blue_bright, chip_blue_bg
                else:
                    tier, tier_color, tier_bg = "WATCHING", c_grey_mid, chip_grey_bg

                border_col = c_green if "HIGH" in tier else c_amber if "CONFIRMED" in tier else c_blue_bright if "EARLY" in tier else c_grey_mid

                rsi_str = ""
                if rsi:
                    rsi_val   = float(rsi)
                    rsi_color = c_green if rsi_val < 60 else c_amber if rsi_val < 75 else c_red
                    rsi_str   = f'<span style="font-family:\'JetBrains Mono\',monospace;font-size:10px;color:{rsi_color}">RSI {rsi_val:.0f}</span>'

                macd_str = f'<span style="font-size:10px;color:{c_green}">MACD ✓</span>' if macd else ""

                feed_html += (
                    f'<div style="background:linear-gradient(135deg, {c_card} 0%, {border_col}0f 100%);border:1px solid {c_border};border-left:4px solid {border_col};'
                    f'border-radius:8px;padding:10px 14px;margin-bottom:4px;'
                    f'display:flex;align-items:center;gap:12px;">'
                    f'<div style="display:flex;align-items:center;gap:7px;min-width:200px;flex-shrink:0">'
                    f'<span style="font-family:\'JetBrains Mono\',monospace;font-weight:700;color:{c_text};font-size:13px">{pid.replace("-USD","")}</span>'
                    f'<span style="background:{lbg};color:{lco};font-size:9px;padding:2px 6px;border-radius:3px;font-weight:700">{lbl}</span>'
                    f'<span style="font-size:9px;color:{c_sub};background:{c_bg2};padding:2px 5px;border-radius:3px">{tf}</span>'
                    f'</div>'
                    f'<div style="display:flex;align-items:center;gap:8px;min-width:180px;flex-shrink:0">'
                    f'<span style="font-size:9px;background:{tier_bg};color:{tier_color};padding:1px 6px;border-radius:4px;font-weight:700">{tier}</span>'
                    f'{rsi_str}{macd_str}{status_str}'
                    f'</div>'
                    f'<div style="display:flex;align-items:center;gap:8px;flex:1">'
                    f'<span style="font-family:\'JetBrains Mono\',monospace;font-size:11px;color:{c_sub}">entry {safe_price(pr, 6)}</span>'
                    f'<span style="font-family:\'JetBrains Mono\',monospace;font-size:12px;font-weight:700;color:{since_entry_col}">{since_entry_str}</span>'
                    f'</div>'
                    f'<div style="display:flex;align-items:center;gap:14px;flex-shrink:0">'
                    f'<span style="font-size:11px;color:{c_sub}">{vol:.1f}x vol</span>'
                    f'<span style="font-size:11px;color:{c24c}">24hr {c24:+.1f}%</span>'
                    f'<span style="font-size:10px;color:{c_sub};min-width:55px;text-align:right">{ts}</span>'
                    f'</div>'
                    f'</div>'
                )
                shown += 1
            st.markdown(f"""
            <style>.feed-scroll::-webkit-scrollbar{{display:none}}</style>
            <div class="feed-scroll" style="height:580px;overflow-y:scroll;padding:24px 2px;
                -webkit-mask-image:linear-gradient(to bottom,transparent 0%,black 10%,black 90%,transparent 100%);
                mask-image:linear-gradient(to bottom,transparent 0%,black 10%,black 90%,transparent 100%);
                scrollbar-width:none;">
            {feed_html}
            </div>""", unsafe_allow_html=True)
        else:
            st.info("No signals found in the last 24 hours.")

    # ── COIN DETAIL ────────────────────────────────────────────────────────────
    with tab_d:
        coins = sorted(states_df["product_id"].tolist()) if not states_df.empty else []
        sel = st.selectbox("Select coin", coins if coins else ["No data yet"])
        st.markdown('<div class="sec-hdr"><span class="sec-hdr-title">Coin Detail</span><div class="sec-hdr-line"></div></div>', unsafe_allow_html=True)

        if sel and sel != "No data yet" and not states_df.empty:
            cs = states_df[states_df["product_id"] == sel]
            if not cs.empty:
                s      = cs.iloc[0]
                c24    = float(s.get("change_24hr", 0) or 0)
                pr     = float(s.get("current_price", 0) or 0)
                peak   = float(s.get("peak_price", 0) or 0)
                l2p    = float(s.get("l2_price") or 0)
                trail  = float(s.get("trailing_high") or 0)
                accel  = int(s.get("accel_count", 0) or 0)
                rfl    = float(s.get("range_from_low", 0) or 0)
                rsi    = s.get("rsi")
                macd_b = bool(s.get("macd_bullish") or False)
                ema_ok = bool(s.get("price_above_ema20") and s.get("ema20_above_ema50"))
                rs     = float(s.get("rs_vs_btc") or 0)
                ml     = str(s.get("multi_leg_state") or "")
                tier_label, tier_color, tier_bg = signal_tier(s)
                tier_colors_map = {
                    "HIGH CONVICTION": c_green,
                    "CONFIRMED":       c_amber_bright,
                    "EARLY SIGNAL":    c_blue_bright,
                    "WATCHING":        c_grey_mid,
                }
                tier_display_color = tier_colors_map.get(tier_label, c_grey_mid)
                hl_color = c_blue_bright if "CONFIRMED" in ml else c_amber if "PRE_BREAKOUT" in ml else c_sub
                c24c   = c_green if c24 > 0 else c_red

                current_gain = round((pr - l2p) / l2p * 100, 1) if l2p > 0 and not math.isnan(pr) and not math.isnan(l2p) else 0
                peak_gain    = round((peak - l2p) / l2p * 100, 1) if l2p > 0 and peak > 0 and not math.isnan(peak) else 0
                trail_gain   = round((trail - l2p) / l2p * 100, 1) if l2p > 0 and trail > 0 and not math.isnan(trail) else 0
                cg_color     = c_green if current_gain > 0 else c_red if current_gain < 0 else c_sub
                pg_color     = c_green if peak_gain >= 0 else c_red

                if s.get("tp2_hit"):
                    tpsl_label = "EXITED";    tpsl_bg, tpsl_color, tpsl_border = chip_green_bg, chip_green_text, c_green
                elif s.get("sl_hit"):
                    tpsl_label = "STOPPED";   tpsl_bg, tpsl_color, tpsl_border = chip_red_bg, chip_red_text, c_red
                elif s.get("time_stop_hit"):
                    tpsl_label = "TIME STOP"; tpsl_bg, tpsl_color, tpsl_border = chip_grey_bg, chip_grey_text, c_grey_mid
                elif s.get("tp1_hit"):
                    tpsl_label = "TP1 HIT";   tpsl_bg, tpsl_color, tpsl_border = chip_amber_bg, chip_amber_text, c_amber
                elif s.get("l2_fired"):
                    tpsl_label = "OPEN";      tpsl_bg, tpsl_color, tpsl_border = chip_green_bg, chip_green_text, c_green
                else:
                    tpsl_label = "NO L2";     tpsl_bg, tpsl_color, tpsl_border = chip_grey_bg, chip_grey_text, c_grey_mid

                st.markdown(f"""
                <div style="display:grid;grid-template-columns:repeat(8,1fr);gap:8px;margin-bottom:12px">
                  <div style="background:linear-gradient(145deg, {c_card} 0%, {tier_display_color}0d 100%);border:1px solid {c_border};border-radius:8px;padding:10px 12px;text-align:center">
                    <div style="font-family:'JetBrains Mono',monospace;font-size:13px;font-weight:600;color:{c_text}">{safe_price(pr)}</div>
                    <div style="font-size:9px;color:{c_sub};text-transform:uppercase;letter-spacing:0.1em;margin-top:3px">Price</div>
                  </div>
                  <div style="background:linear-gradient(145deg, {c_card} 0%, {tier_display_color}0d 100%);border:1px solid {c_border};border-radius:8px;padding:10px 12px;text-align:center">
                    <div style="font-family:'JetBrains Mono',monospace;font-size:13px;font-weight:600;color:{c24c}">{c24:+.1f}%</div>
                    <div style="font-size:9px;color:{c_sub};text-transform:uppercase;letter-spacing:0.1em;margin-top:3px">24hr</div>
                  </div>
                  <div style="background:linear-gradient(145deg, {c_card} 0%, {tier_display_color}0d 100%);border:1px solid {c_border};border-radius:8px;padding:10px 12px;text-align:center">
                    <div style="font-family:'JetBrains Mono',monospace;font-size:13px;font-weight:600;color:{c_text}">{safe_price(l2p)}</div>
                    <div style="font-size:9px;color:{c_sub};text-transform:uppercase;letter-spacing:0.1em;margin-top:3px">L2 Entry</div>
                  </div>
                  <div style="background:linear-gradient(145deg, {c_card} 0%, {tier_display_color}0d 100%);border:1px solid {c_border};border-radius:8px;padding:10px 12px;text-align:center">
                    <div style="font-family:'JetBrains Mono',monospace;font-size:13px;font-weight:600;color:{cg_color}">{current_gain:+.1f}%</div>
                    <div style="font-size:9px;color:{c_sub};text-transform:uppercase;letter-spacing:0.1em;margin-top:3px">Since Entry</div>
                  </div>
                  <div style="background:linear-gradient(145deg, {c_card} 0%, {tier_display_color}0d 100%);border:1px solid {c_border};border-radius:8px;padding:10px 12px;text-align:center">
                    <div style="font-family:'JetBrains Mono',monospace;font-size:13px;font-weight:600;color:{c_text}">{safe_price(peak)}</div>
                    <div style="font-size:9px;color:{c_sub};text-transform:uppercase;letter-spacing:0.1em;margin-top:3px">Peak Price</div>
                  </div>
                  <div style="background:linear-gradient(145deg, {c_card} 0%, {tier_display_color}0d 100%);border:1px solid {c_border};border-radius:8px;padding:10px 12px;text-align:center">
                    <div style="font-family:'JetBrains Mono',monospace;font-size:13px;font-weight:600;color:{pg_color}">{peak_gain:+.1f}%</div>
                    <div style="font-size:9px;color:{c_sub};text-transform:uppercase;letter-spacing:0.1em;margin-top:3px">Peak Gain</div>
                  </div>
                  <div style="background:linear-gradient(145deg, {c_card} 0%, {tier_display_color}0d 100%);border:1px solid {c_border};border-radius:8px;padding:10px 12px;text-align:center">
                    <div style="font-family:'JetBrains Mono',monospace;font-size:13px;font-weight:600;color:{c_green if trail > 0 else c_sub}">{f"+{trail_gain:.1f}%" if trail > 0 else "—"}</div>
                    <div style="font-size:9px;color:{c_sub};text-transform:uppercase;letter-spacing:0.1em;margin-top:3px">Trail High</div>
                  </div>
                  <div style="background:{tpsl_bg};border:1px solid {c_border};border-left:4px solid {tpsl_border};border-radius:8px;padding:10px 12px;text-align:center">
                    <div style="font-family:'JetBrains Mono',monospace;font-size:12px;font-weight:700;color:{tpsl_color}">{tpsl_label}</div>
                    <div style="font-size:9px;color:{c_sub};text-transform:uppercase;letter-spacing:0.1em;margin-top:3px">Status</div>
                  </div>
                </div>
                """, unsafe_allow_html=True)

                st.markdown(f"""
                <div style="background:linear-gradient(135deg, {c_bg2} 0%, {tier_display_color}1a 100%);border:1px solid {c_border};border-left:4px solid {tier_display_color};border-radius:10px;padding:12px 16px;margin-bottom:10px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
                  <div style="display:flex;flex-direction:column;align-items:center;gap:2px;flex:1">
                    {badge(s.get('classification',''), str(s.get('l2_type','') or ''))}
                    <span style="font-size:9px;color:{c_sub};text-transform:uppercase;letter-spacing:0.1em;margin-top:2px">Classification</span>
                  </div>
                  <div style="display:flex;flex-direction:column;align-items:center;gap:2px;flex:1">
                    <span style="font-size:12px;font-weight:700;color:{tier_display_color};letter-spacing:0.06em">{tier_label}</span>
                    <span style="font-size:9px;color:{c_sub};text-transform:uppercase;letter-spacing:0.1em">Signal tier</span>
                  </div>
                  <div style="display:flex;flex-direction:column;align-items:center;gap:2px;flex:1">
                    <strong style="font-size:13px;color:{c_text}">{accel}</strong>
                    <span style="font-size:9px;color:{c_sub};text-transform:uppercase;letter-spacing:0.1em">Accel</span>
                  </div>
                  <div style="display:flex;flex-direction:column;align-items:center;gap:2px;flex:1">
                    <strong style="font-size:13px;color:{c_green if s.get('l2_fired') else c_sub}">{'Yes' if s.get('l2_fired') else 'No'}</strong>
                    <span style="font-size:9px;color:{c_sub};text-transform:uppercase;letter-spacing:0.1em">L2</span>
                  </div>
                  <div style="display:flex;flex-direction:column;align-items:center;gap:2px;flex:1">
                    <strong style="font-size:13px;color:{c_red if s.get('dump_fired') else c_sub}">{'Yes' if s.get('dump_fired') else 'No'}</strong>
                    <span style="font-size:9px;color:{c_sub};text-transform:uppercase;letter-spacing:0.1em">Dump</span>
                  </div>
                  <div style="display:flex;flex-direction:column;align-items:center;gap:2px;flex:1">
                    <strong style="font-size:13px;color:{c_green}">+{rfl:.1f}%</strong>
                    <span style="font-size:9px;color:{c_sub};text-transform:uppercase;letter-spacing:0.1em">From low</span>
                  </div>
                  {f'<div style="display:flex;flex-direction:column;align-items:center;gap:2px;flex:1"><strong style="font-size:13px;color:{hl_color}">{ml}</strong><span style="font-size:9px;color:{c_sub};text-transform:uppercase;letter-spacing:0.1em">HH/HL</span></div>' if ml and ml != "nan" and ml != "None" else ''}
                  {f'<div style="display:flex;flex-direction:column;align-items:center;gap:2px;flex:1"><strong style="font-size:13px;color:{c_purple}">{float(s.get("coil_range_pct",0) or 0):.1f}%</strong><span style="font-size:9px;color:{c_sub};text-transform:uppercase;letter-spacing:0.1em">Coiling</span></div>' if s.get("coiling") else ''}
                </div>
                """, unsafe_allow_html=True)

                rsi_val = float(rsi) if rsi is not None else None
                if rsi_val is not None and math.isnan(rsi_val): rsi_val = None
                if rsi_val is None:
                    rsi_color, rsi_lbl = c_sub, "RSI —"
                elif rsi_val < 45:
                    rsi_color, rsi_lbl = c_green, f"RSI {rsi_val:.0f} — fresh"
                elif rsi_val < 60:
                    rsi_color, rsi_lbl = c_amber, f"RSI {rsi_val:.0f} — building"
                elif rsi_val < 75:
                    rsi_color, rsi_lbl = c_amber_bright, f"RSI {rsi_val:.0f} — extended"
                else:
                    rsi_color, rsi_lbl = c_red, f"RSI {rsi_val:.0f} — overbought"

                macd_col = c_green if macd_b else c_sub
                macd_lbl = "Bullish cross" if macd_b else "No cross yet"

                if s.get("price_above_ema20") and s.get("ema20_above_ema50"):
                    ema_col, ema_lbl = c_green, "Bull structure"
                elif s.get("price_above_ema20"):
                    ema_col, ema_lbl = c_amber, "Above EMA20"
                else:
                    ema_col, ema_lbl = c_sub, "Below EMA20"

                rs_safe = float(rs) if rs is not None else 0.0
                if math.isnan(rs_safe): rs_safe = 0.0
                if rs_safe > 10:
                    rs_color = c_green
                elif rs_safe > 3:
                    rs_color = c_amber
                elif rs_safe > 0:
                    rs_color = c_sub
                else:
                    rs_color = c_red
                rs_lbl = f"RS/BTC {rs_safe:+.1f}%" if rs is not None else "RS/BTC —"

                st.markdown(f"""
                <div style="background:linear-gradient(135deg, {c_bg2} 0%, {rsi_color}1a 100%);border:1px solid {c_border};border-left:4px solid {rsi_color};border-radius:10px;padding:12px 16px;margin-bottom:16px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
                  <div style="display:flex;flex-direction:column;align-items:center;gap:2px;flex:1">
                    <div style="font-family:'JetBrains Mono',monospace;font-size:14px;font-weight:600;color:{rsi_color}">{rsi_lbl}</div>
                    <div style="font-size:9px;color:{c_sub};text-transform:uppercase;letter-spacing:0.1em">Momentum</div>
                  </div>
                  <div style="display:flex;flex-direction:column;align-items:center;gap:2px;flex:1">
                    <div style="font-size:13px;font-weight:600;color:{macd_col}">{macd_lbl}</div>
                    <div style="font-size:9px;color:{c_sub};text-transform:uppercase;letter-spacing:0.1em">MACD 12/26/9</div>
                  </div>
                  <div style="display:flex;flex-direction:column;align-items:center;gap:2px;flex:1">
                    <div style="font-size:13px;font-weight:600;color:{ema_col}">{ema_lbl}</div>
                    <div style="font-size:9px;color:{c_sub};text-transform:uppercase;letter-spacing:0.1em">EMA 20/50</div>
                  </div>
                  <div style="display:flex;flex-direction:column;align-items:center;gap:2px;flex:1">
                    <div style="font-family:'JetBrains Mono',monospace;font-size:14px;font-weight:600;color:{rs_color}">{rs_lbl}</div>
                    <div style="font-size:9px;color:{c_sub};text-transform:uppercase;letter-spacing:0.1em">vs BTC</div>
                  </div>
                </div>
                """, unsafe_allow_html=True)

            sig_col1, sig_col2 = st.columns([1, 1])
            with sig_col1:
                sig_filter = st.radio("Show", ["L2 only", "All signals"], horizontal=True, key="sig_toggle")
            with sig_col2:
                sig_sort = st.radio("Sort", ["Most recent", "Oldest"], horizontal=True, key="sig_sort")

            coin_sig_all = fetch_coin_signals(sel)

            if sig_filter == "L2 only":
                coin_sig = coin_sig_all[coin_sig_all["level"].astype(str) == "2"] if not coin_sig_all.empty else coin_sig_all
            else:
                coin_sig = coin_sig_all

            if not coin_sig.empty:
                coin_sig = coin_sig.sort_values("triggered_at", ascending=(sig_sort == "Oldest"))

            if not coin_sig.empty:
                st.markdown(f'<div class="sec-hdr"><span class="sec-hdr-title" style="font-size:16px">Signal History</span><div class="sec-hdr-line"></div><span class="sec-hdr-meta">{len(coin_sig)} {"signal" if len(coin_sig) == 1 else "signals"}</span></div>', unsafe_allow_html=True)
                hist_rsi     = s.get("rsi")
                hist_rsi_val = float(hist_rsi) if hist_rsi is not None else None
                if hist_rsi_val is not None and math.isnan(hist_rsi_val):
                    hist_rsi_val = None
                if hist_rsi_val is not None:
                    if hist_rsi_val < 45:
                        hist_rsi_color, hist_rsi_lbl = c_green, f"RSI {hist_rsi_val:.0f}"
                    elif hist_rsi_val < 60:
                        hist_rsi_color, hist_rsi_lbl = c_amber, f"RSI {hist_rsi_val:.0f}"
                    elif hist_rsi_val < 75:
                        hist_rsi_color, hist_rsi_lbl = c_amber_bright, f"RSI {hist_rsi_val:.0f}"
                    else:
                        hist_rsi_color, hist_rsi_lbl = c_red, f"RSI {hist_rsi_val:.0f}"
                    rsi_span = f'<span style="font-family:\'JetBrains Mono\',monospace;font-size:11px;font-weight:600;color:{hist_rsi_color}">{hist_rsi_lbl}</span>'
                else:
                    rsi_span = f'<span style="font-size:11px;color:{c_sub}">RSI —</span>'

                hist_html = ""
                for _, row in coin_sig.iterrows():
                    chg  = float(row.get("price_change", 0) or 0)
                    vol  = float(row.get("volume_ratio", 0) or 0)
                    c24  = float(row.get("change_24hr", 0) or 0)
                    pr   = float(row.get("price", 0) or 0)
                    lv   = str(row.get("level", "1"))
                    l2t  = str(row.get("l2_type", "") or "")
                    ts   = fmt_time(row.get("triggered_at", ""))
                    tf   = row.get("timeframe", "")
                    cc   = c_green if chg > 0 else c_red
                    c24c = c_green if c24 > 0 else c_red
                    if lv == "2" and l2t == "volume":
                        lvbg, lvco, lvlbl = chip_red_bg, chip_red_text, "L2 VOL"
                        hist_border = c_green
                    elif lv == "2" and l2t == "accel":
                        lvbg, lvco, lvlbl = chip_amber_bg, c_amber, "L2 ACCEL"
                        hist_border = c_amber
                    elif lv == "2":
                        lvbg, lvco, lvlbl = chip_red_bg, chip_red_text, "L2"
                        hist_border = c_blue_bright
                    else:
                        lvbg, lvco, lvlbl = chip_grey_bg, chip_grey_text, f"L{lv}"
                        hist_border = c_grey_mid
                    hist_html += (
                        f'<div style="background:linear-gradient(135deg, {c_card} 0%, {hist_border}0f 100%);border:1px solid {c_border};border-left:4px solid {hist_border};border-radius:8px;padding:10px 14px;margin-bottom:4px;display:flex;align-items:center;gap:16px">'
                        f'<span style="font-size:10px;color:{c_sub};min-width:55px">{ts}</span>'
                        f'<span style="background:{lvbg};color:{lvco};font-size:9px;padding:2px 6px;border-radius:3px;font-weight:700;flex-shrink:0">{lvlbl}</span>'
                        f'<span style="font-size:9px;color:{c_sub};background:{c_bg2};padding:2px 5px;border-radius:3px;flex-shrink:0">{tf}</span>'
                        f'<span style="color:{cc};font-family:\'JetBrains Mono\',monospace;font-weight:600;font-size:12px">{chg:+.2f}%</span>'
                        f'<span style="color:{c_sub};font-size:11px">{vol:.1f}x vol</span>'
                        f'{rsi_span}'
                        f'<span style="color:{c24c};font-size:11px">24hr {c24:+.1f}%</span>'
                        f'<span style="color:{c_sub};font-family:\'JetBrains Mono\',monospace;font-size:11px;margin-left:auto">{safe_price(pr)}</span>'
                        f'</div>'
                    )
                st.markdown(f"""
                <style>.hist-scroll::-webkit-scrollbar{{display:none}}</style>
                <div class="hist-scroll" style="height:400px;overflow-y:scroll;padding:4px 2px;
                    -webkit-mask-image:linear-gradient(to bottom,transparent 0%,black 5%,black 95%,transparent 100%);
                    mask-image:linear-gradient(to bottom,transparent 0%,black 5%,black 95%,transparent 100%);
                    scrollbar-width:none;">
                {hist_html}
                </div>""", unsafe_allow_html=True)
            else:
                st.markdown(f'<div style="text-align:center;padding:32px;color:{c_sub};font-size:12px">No {"L2 " if sig_filter == "L2 only" else ""}signals found for {sel}</div>', unsafe_allow_html=True)

    # ── LEADERBOARD ────────────────────────────────────────────────────────────
    with tab_l:
        st.markdown(f'<div class="sec-hdr"><span class="sec-hdr-title">Leaderboard</span><div class="sec-hdr-line"></div></div>', unsafe_allow_html=True)
        time_window = st.radio("Time window", ["3hr","12hr","24hr"], index=2, horizontal=True, key="lb_time")
        hours = {"3hr":3,"12hr":12,"24hr":24}[time_window]

        if states_df.empty:
            st.info("No data yet.")
        else:
            if time_window == "24hr":
                ranked = states_df.copy(); ranked["pct_change"] = ranked["change_24hr"]
            else:
                @st.cache_data(ttl=60)
                def fetch_leaderboard(h):
                    try:
                        cutoff = (datetime.utcnow()-timedelta(hours=h)).isoformat()
                        res = supabase.table("momentum_history").select("product_id,price,recorded_at").gte("recorded_at",cutoff).order("recorded_at",desc=False).execute()
                        return pd.DataFrame(res.data) if res.data else pd.DataFrame()
                    except: return pd.DataFrame()
                hist = fetch_leaderboard(hours)
                if hist.empty: st.info(f"Not enough history for {time_window} yet."); hist=None
                else:
                    earliest = hist.groupby("product_id").first().reset_index()[["product_id","price"]].rename(columns={"price":"price_start"})
                    latest   = hist.groupby("product_id").last().reset_index()[["product_id","price"]].rename(columns={"price":"price_end"})
                    merged   = earliest.merge(latest,on="product_id")
                    merged["pct_change"] = ((merged["price_end"]-merged["price_start"])/merged["price_start"]*100).round(2)
                    ranked = merged.merge(states_df[["product_id","l2_fired","accel_count","current_price"]],on="product_id",how="left")

            if time_window=="24hr" or (time_window!="24hr" and hist is not None and not hist.empty):
                cl,cr = st.columns(2)
                min_pct = 15 if time_window=="24hr" else 3

                with cl:
                    st.markdown(f'<p style="font-size:11px;font-weight:700;color:{c_text};margin-bottom:10px;text-transform:uppercase;letter-spacing:0.1em">Top Gainers · {time_window}</p>', unsafe_allow_html=True)
                    gainers = ranked[ranked["pct_change"]>=min_pct].sort_values("pct_change",ascending=False).head(10)
                    if not gainers.empty:
                        for i,(_,row) in enumerate(gainers.iterrows(),1):
                            pct   = float(row.get("pct_change",0) or 0)
                            price = float(row.get("current_price",0) or 0)
                            l2b   = f'<span style="font-size:9px;color:{c_gold};font-weight:700;margin-right:4px">L2</span>' if row.get("l2_fired") else ''
                            accel = "+"*min(int(row.get("accel_count",0) or 0),3)
                            st.markdown(f"""
                            <div class="leader-row" style="background:linear-gradient(135deg, {c_card} 0%, {c_green}0f 100%);border-left:4px solid {c_green};">
                              <span style="font-size:10px;color:{c_sub};width:20px">#{i}</span>
                              <span style="font-family:'JetBrains Mono',monospace;font-weight:600;color:{c_text};flex:1;margin-left:10px">{row['product_id'].replace('-USD','')}</span>
                              <span style="font-size:11px;margin-right:10px">{l2b}{accel}</span>
                              <span style="font-family:'JetBrains Mono',monospace;font-size:12px;color:{c_sub};margin-right:12px">{safe_price(price)}</span>
                              <span style="color:{c_green};font-family:'JetBrains Mono',monospace;font-weight:700">{pct:+.2f}%</span>
                            </div>
                            """, unsafe_allow_html=True)
                    else: st.info(f"No gainers above {min_pct}% right now.")

                with cr:
                    st.markdown(f'<p style="font-size:11px;font-weight:700;color:{c_text};margin-bottom:10px;text-transform:uppercase;letter-spacing:0.1em">Top Losers · {time_window}</p>', unsafe_allow_html=True)
                    losers = ranked[ranked["pct_change"]<=-3].sort_values("pct_change",ascending=True).head(10)
                    if not losers.empty:
                        for i,(_,row) in enumerate(losers.iterrows(),1):
                            pct   = float(row.get("pct_change",0) or 0)
                            price = float(row.get("current_price",0) or 0)
                            st.markdown(f"""
                            <div class="leader-row" style="background:linear-gradient(135deg, {c_card} 0%, {c_red}0f 100%);border-left:4px solid {c_red};">
                              <span style="font-size:10px;color:{c_sub};width:20px">#{i}</span>
                              <span style="font-family:'JetBrains Mono',monospace;font-weight:600;color:{c_text};flex:1;margin-left:10px">{row['product_id'].replace('-USD','')}</span>
                              <span style="font-family:'JetBrains Mono',monospace;font-size:12px;color:{c_sub};margin-right:12px">{safe_price(price)}</span>
                              <span style="color:{c_red};font-family:'JetBrains Mono',monospace;font-weight:700">{pct:+.2f}%</span>
                            </div>
                            """, unsafe_allow_html=True)
                    else: st.info("No losers below -3% right now.")

    # ── HALL OF FAME ───────────────────────────────────────────────────────────
    with tab_h:
        hof_df = fetch_hall_of_fame()

        st.markdown(f'<div class="sec-hdr"><span class="sec-hdr-title">Hall of Fame</span><div class="sec-hdr-line"></div><span class="sec-hdr-meta">{len(hof_df) if not hof_df.empty else 0} documented wins · since May 24</span></div>', unsafe_allow_html=True)

        if hof_df.empty:
            st.info("No recorded wins yet.")
        else:
            def exit_style(exit_type):
                if exit_type == "TP1_TRAIL":
                    return chip_green_bg, chip_green_text, c_green, "TP1 + TRAIL EXIT"
                elif exit_type == "TIME_STOP":
                    return chip_amber_bg, chip_amber_text, c_amber, "TIME STOP EXIT"
                elif exit_type == "DUMP_EXIT":
                    return chip_blue_bg, chip_blue_text, c_blue, "DUMP SIGNAL EXIT"
                return chip_grey_bg, chip_grey_text, c_grey_mid, exit_type

            # sort by captured gain descending for ranking
            hof_sorted = hof_df.copy()
            hof_sorted["exit_gain"] = hof_sorted["exit_gain"].apply(lambda x: float(x or 0))
            hof_sorted["peak_gain"] = hof_sorted["peak_gain"].apply(lambda x: float(x or 0))
            hof_sorted = hof_sorted.sort_values("exit_gain", ascending=False).reset_index(drop=True)

            # aggregate stats
            total_wins = len(hof_sorted)
            avg_gain   = hof_sorted["exit_gain"].mean()
            best_gain  = hof_sorted["exit_gain"].iloc[0]
            best_coin  = str(hof_sorted["product_id"].iloc[0]).replace("-USD", "")
            avg_peak   = hof_sorted["peak_gain"].mean()
            win_rate_tp1 = (hof_sorted["exit_type"] == "TP1_TRAIL").sum()

            # rank badge colors
            rank_colors = {1: c_gold, 2: "#A8A8A8", 3: "#CD7F32"}

            # ── stats banner ──────────────────────────────────────────────────
            st.markdown(f"""
            <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:24px">
              <div style="background:linear-gradient(145deg, {c_card} 0%, rgba(184,146,58,0.10) 100%);border:none;box-shadow:0 2px 12px rgba(0,0,0,0.12);border-radius:12px;padding:18px 20px;text-align:center">
                <div style="font-family:'JetBrains Mono',monospace;font-size:36px;font-weight:700;color:{c_gold};line-height:1">{total_wins}</div>
                <div style="font-size:9px;color:{c_sub};text-transform:uppercase;letter-spacing:0.14em;margin-top:6px">Total Wins</div>
              </div>
              <div style="background:linear-gradient(145deg, {c_card} 0%, rgba(184,146,58,0.10) 100%);border:none;box-shadow:0 2px 12px rgba(0,0,0,0.12);border-radius:12px;padding:18px 20px;text-align:center">
                <div style="font-family:'JetBrains Mono',monospace;font-size:36px;font-weight:700;color:{c_gold};line-height:1">{avg_gain:+.1f}%</div>
                <div style="font-size:9px;color:{c_sub};text-transform:uppercase;letter-spacing:0.14em;margin-top:6px">Avg Captured</div>
              </div>
              <div style="background:linear-gradient(145deg, {c_card} 0%, rgba(184,146,58,0.10) 100%);border:none;box-shadow:0 2px 12px rgba(0,0,0,0.12);border-radius:12px;padding:18px 20px;text-align:center">
                <div style="font-family:'JetBrains Mono',monospace;font-size:36px;font-weight:700;color:{c_gold};line-height:1">{best_gain:+.1f}%</div>
                <div style="font-size:9px;color:{c_sub};text-transform:uppercase;letter-spacing:0.14em;margin-top:6px">Best Trade · {best_coin}</div>
              </div>
              <div style="background:linear-gradient(145deg, {c_card} 0%, rgba(184,146,58,0.10) 100%);border:none;box-shadow:0 2px 12px rgba(0,0,0,0.12);border-radius:12px;padding:18px 20px;text-align:center">
                <div style="font-family:'JetBrains Mono',monospace;font-size:36px;font-weight:700;color:{c_gold};line-height:1">{avg_peak:+.1f}%</div>
                <div style="font-size:9px;color:{c_sub};text-transform:uppercase;letter-spacing:0.14em;margin-top:6px">Avg Peak Detected</div>
              </div>
            </div>
            """, unsafe_allow_html=True)

            # ── card grid ─────────────────────────────────────────────────────
            cols = st.columns(3)
            for i, (_, row) in enumerate(hof_sorted.iterrows()):
                rank      = i + 1
                pid       = str(row.get("product_id", "")).replace("-USD", "")
                exit_gain = float(row.get("exit_gain") or 0)
                peak_gain = float(row.get("peak_gain") or 0)
                exit_type = str(row.get("exit_type") or "")
                fired_at  = row.get("l2_fired_at", "")
                accel     = int(row.get("accel_count") or 0)
                rsi       = row.get("rsi")
                rs        = row.get("rs_vs_btc")
                ebg, eco, border_c, elbl = exit_style(exit_type)

                date_str = ""
                try:
                    dt = datetime.fromisoformat(str(fired_at).replace("Z", "+00:00"))
                    date_str = dt.astimezone(CDMX).strftime("%b %d, %Y")
                except: pass

                rsi_val = float(rsi) if rsi is not None else None
                if rsi_val is not None and math.isnan(rsi_val): rsi_val = None
                if rsi_val is not None:
                    if rsi_val < 45:   rsi_color, rsi_lbl = c_green, f"RSI {rsi_val:.0f} — fresh"
                    elif rsi_val < 60: rsi_color, rsi_lbl = c_amber, f"RSI {rsi_val:.0f} — building"
                    elif rsi_val < 75: rsi_color, rsi_lbl = c_amber_bright, f"RSI {rsi_val:.0f} — extended"
                    else:              rsi_color, rsi_lbl = c_red, f"RSI {rsi_val:.0f} — overbought"
                else:
                    rsi_color, rsi_lbl = c_sub, "RSI —"

                rs_val = float(rs) if rs is not None else 0.0
                if rs_val > 5:   rs_color = c_green
                elif rs_val > 0: rs_color = c_amber
                else:            rs_color = c_red
                rs_lbl = f"RS/BTC {rs_val:+.1f}%" if rs is not None else "RS/BTC —"

                accel_str = f'<span style="font-size:10px;color:{c_gold};font-weight:700">+{accel} accel</span>' if accel > 0 else ""
                rank_color = rank_colors.get(rank, c_sub)
                rank_badge = f'<span style="font-family:\'JetBrains Mono\',monospace;font-size:11px;font-weight:700;color:{rank_color}">#{rank}</span>'

                with cols[i % 3]:
                    st.markdown(f"""
                    <div style="background:linear-gradient(145deg, {c_card} 0%, rgba(184,146,58,0.07) 100%);
                                border:1px solid {c_amber}40;border-top:4px solid {border_c};
                                border-radius:12px;padding:20px;margin-bottom:16px;">
                      <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:14px">
                        <div>
                          <div style="display:flex;align-items:center;gap:8px">
                            <div style="font-family:'JetBrains Mono',monospace;font-size:20px;font-weight:700;color:{c_text}">{pid}</div>
                            {rank_badge}
                          </div>
                          <div style="font-size:10px;color:{c_sub};margin-top:2px">{date_str}</div>
                        </div>
                        <span style="background:{ebg};color:{eco};font-size:9px;padding:3px 8px;border-radius:4px;font-weight:700;letter-spacing:0.04em;text-align:right">{elbl}</span>
                      </div>
                      <div style="margin-bottom:14px">
                        <div style="font-family:'JetBrains Mono',monospace;font-size:40px;font-weight:700;color:{border_c};line-height:1">{exit_gain:+.1f}%</div>
                        <div style="font-size:10px;color:{c_sub};text-transform:uppercase;letter-spacing:0.1em;margin-top:4px">captured gain</div>
                      </div>
                      <div style="border-top:1px solid {c_border};margin-bottom:12px"></div>
                      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
                        <div>
                          <div style="font-family:'JetBrains Mono',monospace;font-size:15px;font-weight:600;color:{c_text}">{peak_gain:+.1f}%</div>
                          <div style="font-size:9px;color:{c_sub};text-transform:uppercase;letter-spacing:0.08em;margin-top:2px">peak detected</div>
                        </div>
                        {accel_str}
                      </div>
                      <div style="border-top:1px solid {c_border};margin-bottom:12px"></div>
                      <div style="display:flex;justify-content:space-between;align-items:center">
                        <span style="font-family:'JetBrains Mono',monospace;font-size:11px;font-weight:600;color:{rsi_color}">{rsi_lbl}</span>
                        <span style="font-family:'JetBrains Mono',monospace;font-size:11px;font-weight:600;color:{rs_color}">{rs_lbl}</span>
                      </div>
                    </div>
                    """, unsafe_allow_html=True)

# ════════════════════════════════════════════════════════════════════════════
# ABOUT
# ════════════════════════════════════════════════════════════════════════════
elif st.session_state.page == "About":
    st.markdown("""<div class="hero-block"><div class="hero-label">About This Project</div><h1 class="hero-title">Built by a trader,<br><em>for traders.</em></h1></div>""", unsafe_allow_html=True)
    st.markdown("""
    <style>
    @keyframes aboutCardIn {
        from { opacity:0; transform:translateY(16px); }
        to   { opacity:1; transform:translateY(0); }
    }
    @keyframes aboutNumPulse {
        0%,100% { color:#B8923A; text-shadow:0 0 0 rgba(184,146,58,0); }
        50%      { color:#D4A853; text-shadow:0 0 12px rgba(212,168,83,0.85); }
    }
    </style>""", unsafe_allow_html=True)
    col_l, col_r = st.columns([1, 1.8])
    with col_l:
        st.markdown(f"""
        <div style="background:linear-gradient(145deg,{c_card} 0%,rgba(184,146,58,0.07) 100%);
                    border:none;border-top:3px solid #B8923A;border-radius:12px;
                    padding:28px 22px;text-align:center;
                    box-shadow:0 2px 12px rgba(0,0,0,0.12);
                    opacity:0;animation:aboutCardIn 0.3s ease forwards;">
          <div style="width:76px;height:76px;border-radius:50%;background:#0E1B2E;
                      margin:0 auto 16px;display:flex;align-items:center;justify-content:center;
                      font-family:'Playfair Display',serif;font-size:26px;color:#D4A853;
                      box-shadow:0 0 0 3px rgba(184,146,58,0.3)">N</div>
          <div style="font-family:'Playfair Display',serif;font-size:18px;font-weight:700;color:{c_text}">Nico</div>
          <div style="font-size:10px;color:{c_sub};text-transform:uppercase;letter-spacing:0.14em;margin-top:3px">Builder · Data · Crypto</div>
          <div style="font-size:12px;color:{c_sub};margin-top:14px;line-height:1.75;text-align:center">Passionate about building tools that turn raw market data into actionable intelligence.</div>
          <div style="display:flex;justify-content:center;flex-wrap:wrap;gap:8px;margin-top:16px">
            <a href="https://nicopxm.me" target="_blank" style="padding:6px 13px;background:linear-gradient(135deg,rgba(184,146,58,0.12),rgba(212,168,83,0.06));border:1px solid #B8923A;border-radius:7px;font-size:11px;color:#B8923A;text-decoration:none;font-weight:600">🌐 nicopxm.me</a>
            <a href="mailto:nicopxm@outlook.com" style="padding:6px 13px;border:1px solid {c_border};border-radius:7px;font-size:11px;color:{c_text};text-decoration:none;font-weight:500">📧 Email</a>
            <a href="https://www.linkedin.com/in/javila95/" target="_blank" style="padding:6px 13px;border:1px solid {c_border};border-radius:7px;font-size:11px;color:{c_text};text-decoration:none;font-weight:500;display:inline-flex;align-items:center;gap:5px"><svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor"><path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433a2.062 2.062 0 0 1-2.063-2.065 2.064 2.064 0 1 1 2.063 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z"/></svg> LinkedIn</a>
<a href="https://github.com/nicopxm" target="_blank" style="padding:6px 13px;border:1px solid {c_border};border-radius:7px;font-size:11px;color:{c_text};text-decoration:none;font-weight:500;display:inline-flex;align-items:center;gap:5px"><svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor"><path d="M12 0C5.374 0 0 5.373 0 12c0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23A11.509 11.509 0 0 1 12 5.803c1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576C20.566 21.797 24 17.3 24 12c0-6.627-5.373-12-12-12z"/></svg> GitHub</a>
          </div>
          <div style="margin-top:18px;display:flex;flex-wrap:wrap;gap:6px;justify-content:center">
            <span class="tech-pill">🐍 Python</span>
            <span class="tech-pill">⚡ Streamlit</span>
            <span class="tech-pill">🗄 Supabase</span>
            <span class="tech-pill">⏱ APScheduler</span>
            <span class="tech-pill">📊 Pandas</span>
            <span class="tech-pill">🔗 Coinbase API</span>
            <span class="tech-pill">✈️ Telegram Bot</span>
            <span class="tech-pill">🐘 PostgreSQL</span>
          </div>
        </div>""", unsafe_allow_html=True)
    with col_r:
        st.markdown(f"""
        <div class="mission-block" style="opacity:0;animation:aboutCardIn 0.3s ease 0.1s forwards;">
          <div style="font-size:10px;letter-spacing:0.18em;text-transform:uppercase;color:rgba(212,168,83,0.75);margin-bottom:13px">Mission</div>
          <div class="mission-quote">"Most traders see the pump after it happened. This system is built to see it while it's building."</div>
          <p style="font-size:13px;color:rgba(247,244,238,0.55);margin-top:16px;line-height:1.8">Born from hours of watching coins rocket 30–100% while missing the entry. Built over 32 days with 29 documented wins and a 3.17:1 risk/reward ratio.</p>
        </div>

        <div style="font-size:10px;letter-spacing:0.18em;text-transform:uppercase;color:{c_amber};margin:16px 0 12px">What this project does</div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:16px">
          <div style="background:linear-gradient(145deg,{c_card} 0%,rgba(184,146,58,0.07) 100%);
                      border:none;border-top:3px solid #B8923A;border-radius:12px;
                      padding:16px 18px;box-shadow:0 2px 12px rgba(0,0,0,0.12);
                      opacity:0;animation:aboutCardIn 0.3s ease 0.2s forwards;">
            <div style="font-family:'JetBrains Mono',monospace;font-size:9px;font-weight:700;
                        letter-spacing:0.18em;text-transform:uppercase;margin-bottom:8px;
                        animation:aboutNumPulse 2.4s ease-in-out infinite">Feature 01</div>
            <div style="font-family:'Playfair Display',serif;font-size:14px;font-weight:600;color:{c_text};margin-bottom:6px">Real-time scanning</div>
            <div style="font-size:12px;color:{c_sub};line-height:1.7">231 pairs · 7 min cycles · 4 timeframes</div>
          </div>
          <div style="background:linear-gradient(145deg,{c_card} 0%,rgba(184,146,58,0.07) 100%);
                      border:none;border-top:3px solid #B8923A;border-radius:12px;
                      padding:16px 18px;box-shadow:0 2px 12px rgba(0,0,0,0.12);
                      opacity:0;animation:aboutCardIn 0.3s ease 0.3s forwards;">
            <div style="font-family:'JetBrains Mono',monospace;font-size:9px;font-weight:700;
                        letter-spacing:0.18em;text-transform:uppercase;margin-bottom:8px;
                        animation:aboutNumPulse 2.4s ease-in-out 0.3s infinite">Feature 02</div>
            <div style="font-family:'Playfair Display',serif;font-size:14px;font-weight:600;color:{c_text};margin-bottom:6px">Multi-layer signals</div>
            <div style="font-size:12px;color:{c_sub};line-height:1.7">Price + volume + acceleration + intraday range</div>
          </div>
          <div style="background:linear-gradient(145deg,{c_card} 0%,rgba(184,146,58,0.07) 100%);
                      border:none;border-top:3px solid #B8923A;border-radius:12px;
                      padding:16px 18px;box-shadow:0 2px 12px rgba(0,0,0,0.12);
                      opacity:0;animation:aboutCardIn 0.3s ease 0.4s forwards;">
            <div style="font-family:'JetBrains Mono',monospace;font-size:9px;font-weight:700;
                        letter-spacing:0.18em;text-transform:uppercase;margin-bottom:8px;
                        animation:aboutNumPulse 2.4s ease-in-out 0.6s infinite">Feature 03</div>
            <div style="font-family:'Playfair Display',serif;font-size:14px;font-weight:600;color:{c_text};margin-bottom:6px">Telegram alerts</div>
            <div style="font-size:12px;color:{c_sub};line-height:1.7">Real-time notifications with Unified Momentum Score 0–100</div>
          </div>
          <div style="background:linear-gradient(145deg,{c_card} 0%,rgba(184,146,58,0.07) 100%);
                      border:none;border-top:3px solid #B8923A;border-radius:12px;
                      padding:16px 18px;box-shadow:0 2px 12px rgba(0,0,0,0.12);
                      opacity:0;animation:aboutCardIn 0.3s ease 0.5s forwards;">
            <div style="font-family:'JetBrains Mono',monospace;font-size:9px;font-weight:700;
                        letter-spacing:0.18em;text-transform:uppercase;margin-bottom:8px;
                        animation:aboutNumPulse 2.4s ease-in-out 0.9s infinite">Feature 04</div>
            <div style="font-family:'Playfair Display',serif;font-size:14px;font-weight:600;color:{c_text};margin-bottom:6px">New listing detector</div>
            <div style="font-size:12px;color:{c_sub};line-height:1.7">Catches new Coinbase listings instantly</div>
          </div>
        </div>

        """, unsafe_allow_html=True)

# ════════════════════════════════════════════════════════════════════════════
# HOW IT WORKS
# ════════════════════════════════════════════════════════════════════════════
elif st.session_state.page == "HowItWorks":
    st.markdown("""<div class="hero-block"><div class="hero-label">Signal Architecture</div><h1 class="hero-title">Six layers of<br><em>signal detection.</em></h1></div>""", unsafe_allow_html=True)
    st.markdown(f"""
    <style>
    @keyframes flowCardIn {{
        from {{ opacity:0; transform:translateY(16px); }}
        to   {{ opacity:1; transform:translateY(0); }}
    }}
    @keyframes connectorIn {{
        from {{ opacity:0; }}
        to   {{ opacity:1; }}
    }}
    @keyframes numPulse {{
        0%,100% {{ color:#B8923A; text-shadow:0 0 0 rgba(184,146,58,0); }}
        50%      {{ color:#D4A853; text-shadow:0 0 12px rgba(212,168,83,0.85); }}
    }}
    @keyframes straightDot {{
        0%   {{ left:-9px; opacity:0; }}
        10%  {{ opacity:1; }}
        90%  {{ opacity:1; }}
        100% {{ left:calc(100% + 9px); opacity:0; }}
    }}
    @keyframes straightBeam {{
        0%   {{ transform:translateX(-150%); opacity:0; }}
        15%  {{ opacity:1; }}
        85%  {{ opacity:1; }}
        100% {{ transform:translateX(350%); opacity:0; }}
    }}
    .fsc {{
        flex:1;
        background:linear-gradient(145deg, {c_card} 0%, rgba(184,146,58,0.07) 100%);
        border:none; border-top:3px solid #B8923A; border-radius:12px;
        padding:22px 18px; min-height:175px;
        box-shadow:0 2px 12px rgba(0,0,0,0.12);
        opacity:0; animation:flowCardIn 0.3s ease forwards;
        transition:box-shadow 0.2s;
    }}
    .fsc:hover {{ box-shadow:0 4px 22px rgba(184,146,58,0.22); }}
    .fsn {{ font-family:'JetBrains Mono',monospace; font-size:10px; font-weight:700;
            letter-spacing:0.18em; text-transform:uppercase; margin-bottom:10px;
            animation:numPulse 2.4s ease-in-out infinite; }}
    .fst {{ font-family:'Playfair Display',serif; font-size:15px; font-weight:600;
            color:{c_text}; margin-bottom:8px; }}
    .fsd {{ font-size:12px; color:{c_sub}; line-height:1.75; }}
    </style>

    <!-- shared SVG glow filter -->
    <svg width="0" height="0" style="position:absolute;overflow:hidden">
      <defs>
        <filter id="dotGlow" x="-80%" y="-80%" width="260%" height="260%">
          <feGaussianBlur stdDeviation="2.5" result="blur"/>
          <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
        </filter>
      </defs>
    </svg>

    <!-- ── Row 1: Steps 01 → 02 → 03  (staircase — each card 36px lower) ── -->
    <div style="display:flex;align-items:flex-start;gap:0;margin-bottom:0;position:relative">

      <!-- Step 01 -->
      <div class="fsc" style="margin-top:0;animation-delay:0.0s">
        <div class="fsn" style="animation-delay:0.0s">Step 01</div>
        <div class="fst">Data Ingestion</div>
        <div class="fsd">Every 7 minutes, live prices, 24hr changes, high/low, and 250 candles fetched from Coinbase for all 231 USD pairs. One batch state read per cycle keeps Supabase egress under 3GB/month.</div>
      </div>

      <!-- Diagonal connector 01 → 02 -->
      <div style="width:44px;flex-shrink:0;align-self:stretch;position:relative;opacity:0;animation:connectorIn 0.3s ease forwards;animation-delay:0.3s">
        <svg width="44" height="280" style="position:absolute;top:0;left:0;overflow:visible">
          <line x1="0" y1="100" x2="44" y2="136" stroke="rgba(184,146,58,0.18)" stroke-width="5" stroke-linecap="round"/>
          <line x1="0" y1="100" x2="44" y2="136" stroke="rgba(184,146,58,0.45)" stroke-width="2" stroke-linecap="round"/>
          <circle r="4" fill="#D4A853" filter="url(#dotGlow)">
            <animate attributeName="opacity" values="0;1;1;0" keyTimes="0;0.1;0.9;1" dur="2.6s" begin="0.4s" repeatCount="indefinite"/>
            <animateMotion path="M 0 100 L 44 136" dur="2.6s" begin="0.4s" repeatCount="indefinite"/>
          </circle>
        </svg>
      </div>

      <!-- Step 02 -->
      <div class="fsc" style="margin-top:36px;animation-delay:0.3s">
        <div class="fsn" style="animation-delay:0.5s">Step 02</div>
        <div class="fst">Price + Volume Detection</div>
        <div class="fsd">Price change across 5min, 15min, 30min, 1hr monitored simultaneously. L1 fires on price threshold breach. L2 upgrades when volume ratio exceeds 1.5x–3.0x average — volume confirmation is the core signal.</div>
      </div>

      <!-- Diagonal connector 02 → 03 -->
      <div style="width:44px;flex-shrink:0;align-self:stretch;position:relative;opacity:0;animation:connectorIn 0.3s ease forwards;animation-delay:0.6s">
        <svg width="44" height="280" style="position:absolute;top:0;left:0;overflow:visible">
          <line x1="0" y1="136" x2="44" y2="172" stroke="rgba(184,146,58,0.18)" stroke-width="5" stroke-linecap="round"/>
          <line x1="0" y1="136" x2="44" y2="172" stroke="rgba(184,146,58,0.45)" stroke-width="2" stroke-linecap="round"/>
          <circle r="4" fill="#D4A853" filter="url(#dotGlow)">
            <animate attributeName="opacity" values="0;1;1;0" keyTimes="0;0.1;0.9;1" dur="2.6s" begin="0.9s" repeatCount="indefinite"/>
            <animateMotion path="M 0 136 L 44 172" dur="2.6s" begin="0.9s" repeatCount="indefinite"/>
          </circle>
        </svg>
      </div>

      <!-- Step 03 -->
      <div class="fsc" style="margin-top:72px;animation-delay:0.6s">
        <div class="fsn" style="animation-delay:1.0s">Step 03</div>
        <div class="fst">Dynamic L2 — Early Detection</div>
        <div class="fsd">When a coin has strong 24hr momentum (≥15%), five safeguards evaluate whether to lower the volume bar: fresh leg test, peak proximity, acceleration required, volume trend, and a separate UNCONFIRMED label so traders know the risk.</div>
      </div>
    </div>

    <!-- ── Straight connector: Step 03 → Step 04 ── -->
    <div style="display:flex;align-items:center;padding:14px 0;position:relative;opacity:0;animation:connectorIn 0.3s ease forwards;animation-delay:0.9s">
      <div style="flex:1;height:2px;position:relative;overflow:hidden;
                  background:linear-gradient(90deg,rgba(184,146,58,0.05),rgba(184,146,58,0.5),rgba(184,146,58,0.05))">
        <div style="position:absolute;top:0;left:0;width:35%;height:100%;
                    background:linear-gradient(90deg,transparent,rgba(212,168,83,0.55),transparent);
                    animation:straightBeam 2.6s ease-in-out 1.4s infinite"></div>
        <div style="position:absolute;top:50%;transform:translateY(-50%);
                    width:7px;height:7px;border-radius:50%;background:#D4A853;
                    box-shadow:0 0 8px 3px rgba(212,168,83,0.6);
                    animation:straightDot 2.6s ease-in-out 1.4s infinite"></div>
      </div>
    </div>

    <!-- ── Row 2: Steps 04 → 05 → 06  (staircase repeats) ── -->
    <div style="display:flex;align-items:flex-start;gap:0;position:relative">

      <!-- Step 04 -->
      <div class="fsc" style="margin-top:0;animation-delay:0.9s">
        <div class="fsn" style="animation-delay:1.3s">Step 04</div>
        <div class="fst">Acceleration + HH/HL Detection</div>
        <div class="fsd">24hr change tracked over 30min, 1hr, 3hr. Consistent growth fires acceleration stages. HH/HL detector reads daily snapshots to identify Higher Highs and Higher Lows — the structural anatomy of a healthy multi-day uptrend.</div>
      </div>

      <!-- Diagonal connector 04 → 05 -->
      <div style="width:44px;flex-shrink:0;align-self:stretch;position:relative;opacity:0;animation:connectorIn 0.3s ease forwards;animation-delay:1.2s">
        <svg width="44" height="280" style="position:absolute;top:0;left:0;overflow:visible">
          <line x1="0" y1="100" x2="44" y2="136" stroke="rgba(184,146,58,0.18)" stroke-width="5" stroke-linecap="round"/>
          <line x1="0" y1="100" x2="44" y2="136" stroke="rgba(184,146,58,0.45)" stroke-width="2" stroke-linecap="round"/>
          <circle r="4" fill="#D4A853" filter="url(#dotGlow)">
            <animate attributeName="opacity" values="0;1;1;0" keyTimes="0;0.1;0.9;1" dur="2.6s" begin="1.8s" repeatCount="indefinite"/>
            <animateMotion path="M 0 100 L 44 136" dur="2.6s" begin="1.8s" repeatCount="indefinite"/>
          </circle>
        </svg>
      </div>

      <!-- Step 05 -->
      <div class="fsc" style="margin-top:36px;animation-delay:1.2s">
        <div class="fsn" style="animation-delay:1.7s">Step 05</div>
        <div class="fst">TA Indicators — RSI · MACD · EMA · RS/BTC</div>
        <div class="fsd">RSI-14 (Wilder's smoothing), MACD 12/26/9, EMA 20/50 structure, and Relative Strength vs BTC calculated from existing candle data. Zero additional API calls. All four stored in the database and shown on every L2 alert.</div>
      </div>

      <!-- Diagonal connector 05 → 06 -->
      <div style="width:44px;flex-shrink:0;align-self:stretch;position:relative;opacity:0;animation:connectorIn 0.3s ease forwards;animation-delay:1.5s">
        <svg width="44" height="280" style="position:absolute;top:0;left:0;overflow:visible">
          <line x1="0" y1="136" x2="44" y2="172" stroke="rgba(184,146,58,0.18)" stroke-width="5" stroke-linecap="round"/>
          <line x1="0" y1="136" x2="44" y2="172" stroke="rgba(184,146,58,0.45)" stroke-width="2" stroke-linecap="round"/>
          <circle r="4" fill="#D4A853" filter="url(#dotGlow)">
            <animate attributeName="opacity" values="0;1;1;0" keyTimes="0;0.1;0.9;1" dur="2.6s" begin="2.3s" repeatCount="indefinite"/>
            <animateMotion path="M 0 136 L 44 172" dur="2.6s" begin="2.3s" repeatCount="indefinite"/>
          </circle>
        </svg>
      </div>

      <!-- Step 06 -->
      <div class="fsc" style="margin-top:72px;animation-delay:1.5s">
        <div class="fsn" style="animation-delay:2.0s">Step 06</div>
        <div class="fst">Automated TP/SL Position Management</div>
        <div class="fsd">Five exit types: TP1 (+20% partial), trailing stop (wick-filtered on 1-min closes), dynamic hard stop (-8% standard / -12% grinders), breakeven trigger (peak +12% moves floor to entry), weak signal exit (2hr no traction). Every profitable exit auto-logged to Hall of Fame.</div>
      </div>
    </div>

    <!-- ── Performance stats banner ── -->
    <div class="page-section" style="margin-top:24px">
      <div style="font-size:10px;letter-spacing:0.18em;text-transform:uppercase;color:#B8923A;margin-bottom:16px">Performance · 32 days of live data</div>
      <div style="display:flex;gap:40px;flex-wrap:wrap">
        <div>
          <div style="font-family:'JetBrains Mono',monospace;font-size:24px;font-weight:600;color:#1A7A4A">+43.0%</div>
          <div style="font-size:11px;color:{c_sub};margin-top:4px">avg trail exit · 13 trades</div>
        </div>
        <div>
          <div style="font-family:'JetBrains Mono',monospace;font-size:24px;font-weight:600;color:#1A7A4A">100%</div>
          <div style="font-size:11px;color:{c_sub};margin-top:4px">profitable exits · worst +21.2%</div>
        </div>
        <div>
          <div style="font-family:'JetBrains Mono',monospace;font-size:24px;font-weight:600;color:#1A7A4A">3.17:1</div>
          <div style="font-size:11px;color:{c_sub};margin-top:4px">risk/reward ratio</div>
        </div>
        <div>
          <div style="font-family:'JetBrains Mono',monospace;font-size:24px;font-weight:600;color:#1A7A4A">29</div>
          <div style="font-size:11px;color:{c_sub};margin-top:4px">documented wins · hall of fame</div>
        </div>
        <div>
          <div style="font-family:'JetBrains Mono',monospace;font-size:24px;font-weight:600;color:{c_amber}">{tp1_rate}%</div>
          <div style="font-size:11px;color:{c_sub};margin-top:4px">TP1 rate · {tp1_hits_recent}/{tp1_total_recent} L2s · since Jun 15</div>
          <div style="font-size:10px;color:{c_sub};margin-top:2px">was 3.4% pre-fix → improving</div>
        </div>
        <div>
          <div style="font-family:'JetBrains Mono',monospace;font-size:24px;font-weight:600;color:{c_text}">231</div>
          <div style="font-size:11px;color:{c_sub};margin-top:4px">pairs monitored</div>
          <div style="font-size:10px;color:{c_sub};margin-top:2px">Coinbase USD · 7 min cycles</div>
        </div>
      </div>
    </div>
    """, unsafe_allow_html=True)

# ════════════════════════════════════════════════════════════════════════════
# CONTACT
# ════════════════════════════════════════════════════════════════════════════
elif st.session_state.page == "Contact":
    st.markdown("""<div class="hero-block"><div class="hero-label">Get In Touch</div><h1 class="hero-title">Let's talk<br><em>data & crypto.</em></h1></div>""", unsafe_allow_html=True)
    st.markdown("""
    <style>
    @keyframes contactCardIn {
        from { opacity:0; transform:translateY(16px); }
        to   { opacity:1; transform:translateY(0); }
    }
    @keyframes contactIconPulse {
        0%,100% { color:#B8923A; text-shadow:0 0 0 rgba(184,146,58,0); }
        50%      { color:#D4A853; text-shadow:0 0 12px rgba(212,168,83,0.85); }
    }
    </style>""", unsafe_allow_html=True)
    st.markdown(f"""
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:4px">

      <!-- Email -->
      <div style="background:linear-gradient(145deg,{c_card} 0%,rgba(184,146,58,0.07) 100%);
                  border:none;border-top:3px solid #B8923A;border-radius:12px;
                  padding:22px 20px;box-shadow:0 2px 12px rgba(0,0,0,0.12);
                  opacity:0;animation:contactCardIn 0.3s ease 0.05s forwards;">
        <div style="font-family:'JetBrains Mono',monospace;font-size:9px;font-weight:700;
                    letter-spacing:0.18em;text-transform:uppercase;margin-bottom:10px;
                    animation:contactIconPulse 2.4s ease-in-out infinite">📧 Email</div>
        <div style="font-family:'Playfair Display',serif;font-size:15px;font-weight:600;color:{c_text};margin-bottom:7px">Direct contact</div>
        <div style="font-size:12px;color:{c_sub};line-height:1.75">Best way to reach me for collaborations, questions, or feedback.</div>
        <a href="mailto:nicopxm@outlook.com" style="display:inline-block;margin-top:12px;font-size:11px;font-weight:600;color:#B8923A;text-decoration:none;border-bottom:1px solid rgba(212,168,83,0.4);padding-bottom:1px">nicopxm@outlook.com →</a>
      </div>

      <!-- GitHub -->
      <div style="background:linear-gradient(145deg,{c_card} 0%,rgba(184,146,58,0.07) 100%);
                  border:none;border-top:3px solid #B8923A;border-radius:12px;
                  padding:22px 20px;box-shadow:0 2px 12px rgba(0,0,0,0.12);
                  opacity:0;animation:contactCardIn 0.3s ease 0.15s forwards;">
        <div style="font-family:'JetBrains Mono',monospace;font-size:9px;font-weight:700;
                    letter-spacing:0.18em;text-transform:uppercase;margin-bottom:10px;
                    animation:contactIconPulse 2.4s ease-in-out 0.3s infinite">💻 GitHub</div>
        <div style="font-family:'Playfair Display',serif;font-size:15px;font-weight:600;color:{c_text};margin-bottom:7px">Private repository</div>
        <div style="font-size:12px;color:{c_sub};line-height:1.75">Scanner, signal logic, dashboard, and Supabase schema. Access by request.</div>
        <a href="https://github.com/nicopxm" target="_blank" style="display:inline-block;margin-top:12px;font-size:11px;font-weight:600;color:#B8923A;text-decoration:none;border-bottom:1px solid rgba(212,168,83,0.4);padding-bottom:1px">github.com/nicopxm →</a>
      </div>

      <!-- LinkedIn -->
      <div style="background:linear-gradient(145deg,{c_card} 0%,rgba(184,146,58,0.07) 100%);
                  border:none;border-top:3px solid #B8923A;border-radius:12px;
                  padding:22px 20px;box-shadow:0 2px 12px rgba(0,0,0,0.12);
                  opacity:0;animation:contactCardIn 0.3s ease 0.25s forwards;">
        <div style="font-family:'JetBrains Mono',monospace;font-size:9px;font-weight:700;
                    letter-spacing:0.18em;text-transform:uppercase;margin-bottom:10px;
                    animation:contactIconPulse 2.4s ease-in-out 0.6s infinite">💼 LinkedIn</div>
        <div style="font-family:'Playfair Display',serif;font-size:15px;font-weight:600;color:{c_text};margin-bottom:7px">Professional network</div>
        <div style="font-size:12px;color:{c_sub};line-height:1.75">Connect for professional opportunities, collaborations, and career updates.</div>
        <a href="https://www.linkedin.com/in/javila95/" target="_blank" style="display:inline-block;margin-top:12px;font-size:11px;font-weight:600;color:#B8923A;text-decoration:none;border-bottom:1px solid rgba(212,168,83,0.4);padding-bottom:1px">linkedin.com/in/javila95 →</a>
      </div>

      <!-- Telegram Channel -->
      <div style="background:linear-gradient(145deg,{c_card} 0%,rgba(184,146,58,0.07) 100%);
                  border:none;border-top:3px solid #B8923A;border-radius:12px;
                  padding:22px 20px;box-shadow:0 2px 12px rgba(0,0,0,0.12);
                  opacity:0;animation:contactCardIn 0.3s ease 0.35s forwards;">
        <div style="font-family:'JetBrains Mono',monospace;font-size:9px;font-weight:700;
                    letter-spacing:0.18em;text-transform:uppercase;margin-bottom:10px;
                    animation:contactIconPulse 2.4s ease-in-out 0.9s infinite">📱 Telegram Channel</div>
        <div style="font-family:'Playfair Display',serif;font-size:15px;font-weight:600;color:{c_text};margin-bottom:7px">Live signal feed</div>
        <div style="font-size:12px;color:{c_sub};line-height:1.75">See live L2 momentum alerts in real time — Unified Momentum Score, RSI, MACD, and automated TP/SL tracking.</div>
        <a href="https://t.me/MomentumAlphaSignals" target="_blank" style="display:inline-block;margin-top:12px;font-size:11px;font-weight:600;color:#B8923A;text-decoration:none;border-bottom:1px solid rgba(212,168,83,0.4);padding-bottom:1px">Join Channel →</a>
      </div>

    </div>""", unsafe_allow_html=True)

st.markdown(f'<div class="footer-text">MOMENTUM · Scanning 231 pairs · {datetime.now(timezone.utc).astimezone(CDMX).strftime("%I:%M %p")} · Coinbase Advanced API</div>', unsafe_allow_html=True)