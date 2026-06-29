---
name: momentum-optimizer
description: >
  Optimize and enhance code and UI for the Momentum crypto signal tracker project.
  Use this skill whenever the user asks to optimize, improve, refactor, clean up,
  or enhance any part of main.py, dashboard_v2.py, or ingestion.py.
  Also use when the user asks to fix bugs, reduce egress, improve performance,
  add NaN guards, improve colors, fix layouts, add cards, update KPIs, or make
  the dashboard look better. Trigger on any request involving code quality,
  UI design, Streamlit styling, Supabase queries, or Railway performance
  in the context of this project — even if the user doesn't say "skill".
---

# Momentum Optimizer Skill

You are working on **Momentum** — a 24/7 automated crypto momentum tracker scanning
231 Coinbase USD pairs on Railway, writing to Supabase, displayed via Streamlit Cloud,
with Telegram alerts to `t.me/MomentumAlphaSignals`.

---

## Project Context

**Stack:**
- `main.py` — APScheduler worker on Railway (~2700 lines). Scans 231 coins every 7 min.
- `dashboard_v2.py` — Streamlit Cloud dashboard (~1200 lines).
- `ingestion.py` — Data ingestion utilities.
- Supabase (PostgreSQL) — primary datastore.
- Python 3.13, Railway worker `intuitive-commitment`, ~$1.90/month.

**Supabase tables:**
- `coin_state` — 231 rows, one per coin. Full position tracking.
- `signals` — historical signal log (timeframe, level, price_change, volume_ratio, l2_type).
- `hall_of_fame` — permanent win record (exit_type, exit_gain, peak_gain, rsi, rs_vs_btc).
- `momentum_history` — price history for leaderboard.
- `daily_snapshots` — HH/HL multi-leg detection.
- `alert_cooldowns` — prevents duplicate Telegram alerts.

**Key constants in main.py:**
```python
TP1_PCT = 20.0
HARD_STOP_STANDARD = -8.0
HARD_STOP_GRINDER = -12.0
TRAILING_STOP_PCT = 12.0
WEAK_SIGNAL_HOURS = 2.0
BREAKEVEN_TRIGGER = 12.0
PUMP_ALERT_THRESHOLD = 3.0
MIN_VOLUME_24H = 50000
```

**Signal tiers:**
- L1 — price momentum detected
- L2 VOL — volume ratio confirmed (1.5x–3.0x)
- L2 ACCEL — acceleration confirmed (accel_count >= 2)
- DYNAMIC L2 — early detection on high 24hr momentum (≥15%)
- HIGH CONVICTION — L2 volume + accel_count >= 1
- CONFIRMED — L2 volume only
- EARLY SIGNAL — dynamic/accel L2

**Exit types in hall_of_fame:**
- `TP1_TRAIL` — TP1 hit (+20%) then trailing stop fired
- `TIME_STOP` — weak signal exit (2hr or 6hr) while profitable
- `DUMP_EXIT` — dump signal fired while position profitable

---

## Color Palette (dashboard_v2.py)

**Always use these variables — never hardcode hex:**

```python
# Theme-aware
c_text   = "#e8e8f0" if dm else "#0E1B2E"
c_sub    = "#888888" if dm else "#6B7280"
c_card   = "#12121a" if dm else "white"
c_border = "#1e1e2e" if dm else "#DDD8CE"
c_bg2    = "#1e1e2e" if dm else "#EDE9DF"
c_green  = "#00ff88" if dm else "#1A7A4A"   # positive / bullish
c_red    = "#ff4444" if dm else "#9B2335"   # negative / bearish
c_gold   = "#D4A853"

# Fixed accents
c_amber        = "#B8923A"   # warning / extended RSI
c_amber_bright = "#FF8F00"   # confirmed tier
c_blue         = "#2979FF"   # HH/HL / early signal
c_purple       = "#7C3AED"   # coiling
c_grey_mid     = "#9E9E9E"   # watching / neutral

# Status chip colors
chip_green_bg   = "#F0FDF4";  chip_green_text = "#166534"
chip_amber_bg   = "#FEF3C7";  chip_amber_text = "#92400E"
chip_red_bg     = "#FEE2E2";  chip_red_text   = "#9B2335"
chip_grey_bg    = "#F3F4F6";  chip_grey_text  = "#6B7280"
chip_blue_bg    = "#DBEAFE";  chip_blue_text  = "#1E40AF"
```

**Color semantics:**
- `c_green` — positive gains, open positions, bullish signals, HIGH CONVICTION tier
- `c_amber` — warnings, extended RSI (60-75), CONFIRMED tier
- `c_amber_bright` — moderate positive, CONFIRMED tier borders
- `c_blue` — EARLY SIGNAL tier, HH/HL labels
- `c_red` — losses, hard stops, negative values, STOPPED status
- `c_grey_mid` — WATCHING tier, neutral states
- `c_gold` — L2 badges, gold accents, nav branding

**Status badge colors:**
- OPEN / EXITED → `chip_green_bg / chip_green_text` with `c_green` border
- TP1 HIT → `chip_amber_bg / chip_amber_text` with `c_amber` border
- STOPPED → `chip_red_bg / chip_red_text` with `c_red` border
- TIME STOP / NO L2 → `chip_grey_bg / chip_grey_text` with `c_grey_mid` border

---

## Typography & Fonts

```css
font-family: 'Outfit', sans-serif;        /* body text */
font-family: 'Playfair Display', serif;   /* headings, hero titles */
font-family: 'JetBrains Mono', monospace; /* numbers, prices, stats */
```

**Font size scale:**
- Hero values: 33-40px JetBrains Mono
- Stat card values: 13-20px JetBrains Mono
- Section headers: 18px Playfair Display
- Labels: 9-11px Outfit uppercase with letter-spacing
- Body: 12-14px Outfit

---

## UI Component Patterns

**Metric card (KPI row):**
```python
f'''<div class="metric-card-sm" style="width:160px;">
  <div class="metric-card-lbl" style="font-size:10px;">{label}</div>
  <div class="metric-card-val" style="font-size:22px;color:{color};">{value}</div>
  <div class="metric-card-sub" style="font-size:10px;color:{sub_color};">{sublabel}</div>
</div>'''
```

**Signal/mover card:**
```python
f'''<div style="background:{c_card};border-top:1px solid {c_border};
  border-right:1px solid {c_border};border-bottom:1px solid {c_border};
  border-left:4px solid {border_col};border-radius:8px;
  padding:10px 14px;margin-bottom:4px;">
  ...content...
</div>'''
```

**Stat card (Coin Detail):**
```python
f'''<div style="background:{c_card};border:1px solid {c_border};
  border-radius:8px;padding:10px 12px;text-align:center">
  <div style="font-family:'JetBrains Mono',monospace;font-size:13px;
    font-weight:600;color:{value_color}">{value}</div>
  <div style="font-size:9px;color:{c_sub};text-transform:uppercase;
    letter-spacing:0.1em;margin-top:3px">{label}</div>
</div>'''
```

**Left border colors by signal tier:**
```python
border_col = c_green if "HIGH" in tier else \
             c_amber_bright if "CONFIRMED" in tier else \
             c_blue if "EARLY" in tier else \
             c_grey_mid
```

---

## Code Optimization Rules

### Supabase / Egress
- **Never** do per-coin SELECT in a loop — always batch: `.select("*").execute()` then build a dict
- Use `.select("col1,col2")` not `.select("*")` when you only need specific columns
- Cache aggressively with `@st.cache_data(ttl=30)` for hot data, `ttl=300` for slow-changing
- Wrap every Supabase call in try/except — never let a DB error crash the scanner
- Current egress target: <3GB/month

### NaN / Null Safety
Always guard before displaying or computing:
```python
import math
val = float(x) if x is not None else None
if val is not None and math.isnan(val): val = None
```

Use `safe_price()` for all price display — never format floats directly.

For `rs_vs_btc` writes:
```python
if rs_vs_btc is not None and not pd.isna(float(rs_vs_btc)):
    state["rs_vs_btc"] = rs_vs_btc
```

### Indicators
- Only write RSI/MACD/EMA to coin_state when `indicators` dict is non-empty AND `df` is not empty
- Never overwrite stored indicator values with None on failed candle fetches
- RSI NaN guard: check `pd.isna(avg_gain) or pd.isna(avg_loss)` before Wilder smoothing

### Signal Logic
- `l2_fired_at` must reset to `now` when `position_was_closed = True` and new L2 fires
- `peak_price` must freeze when `position_closed or time_stop_hit or sl_hit = True`
- `trailing_high` uses `df["close"].iloc[-15:].max()` — never `df["high"]`
- RS/BTC suppression: skip L2 alert if `BTC_CHANGE_24HR >= 3.0 and rs_vs_btc < 5.0`
- Deduplication: one alert per coin per cycle (`coin_best_pump` dict, highest vol_ratio wins)

### Dashboard Performance
- `fetch_market_data()` loads entire `coin_state` once — reuse `states_df` everywhere
- Signal feed deduplication: `drop_duplicates(subset=["product_id", "hour_bucket"])`
- Active Movers filter: `change_24hr >= 5 OR (l2_fired AND not closed)`
- Level comparisons: always `df["level"].astype(str) == "2"` not `== 2`

### Code Cleanliness
- Remove debug logs: `grep -n "DEBUG\|INDICATOR_CHECK\|print(" main.py`
- Constants at top of file in ALL_CAPS
- Wrap Hall of Fame inserts in try/except — never let HOF failure disrupt trading logic
- Verify syntax after every edit: `python3 -m py_compile main.py && echo "✅ OK"`

---

## Performance Benchmarks

| Metric | Current | Target |
|---|---|---|
| TP1 success rate | 8.1% | 30%+ |
| Avg trail exit | +37.7% | Keep >+35% |
| Break-even win rate | 24% | — |
| Egress | ~2.5GB/mo | <3GB/mo |
| Scan cycle | 7 min | — |
| Railway cost | ~$1.90/mo | — |

---

## How to Apply This Skill

### For code optimization requests:
1. Read the relevant file section first
2. Identify: performance bottleneck / egress issue / NaN risk / logic bug
3. Apply the fix following rules above
4. Verify: `python3 -m py_compile main.py && echo "✅ OK"`
5. State what changed and why — one sentence per change

### For UI enhancement requests:
1. Identify which tab/component needs work
2. Use color palette variables — never hardcode hex
3. Use JetBrains Mono for all numbers/prices
4. Use Playfair Display for section headers
5. Keep left border colors semantic (green=bullish, amber=moderate, blue=early, grey=neutral)
6. Test in light mode (dark mode is secondary)
7. Verify with `python3 -m py_compile dashboard_v2.py && echo "✅ OK"`

### Always:
- Make surgical changes — touch only what's needed
- Preserve existing logic — optimize around it, not through it
- Keep Hall of Fame auto-inserts in try/except
- Keep Supabase writes inside try blocks
- Never expose .env values or API keys
