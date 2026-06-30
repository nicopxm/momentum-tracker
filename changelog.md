# Changelog

All notable changes to Momentum (Crypto Signal Tracker) are documented here, in reverse chronological order.

---

## 2026-06-30

### Added — TP0 Partial Profit Tier
**Problem:** TP1 success rate dropped to 5.3% (113 L2s, only 6 hits). Analysis of the 10 most recent missed-TP1 coins showed all 10 peaked above +15% intra-cycle and then fully reversed — 7 went negative, 2 marginal, 1 still open. The system had no mechanism to lock in profit between entry and the full +20% TP1 threshold.

**Fix:** Added a TP0 tier at +15% that sells 25% of the position early, using the same wick-filtered `recent_close_high` intra-cycle check as TP1. Added `tp0_hit`, `tp0_price`, `tp0_fired_at` to `coin_state`. Hall of Fame exit type logic updated to record `TP0_PARTIAL` when TP0 fired but TP1 never did.

**Impact:** Retroactive analysis showed 9 of the last 10 missed-TP1 coins would have converted from a loss to a partial win under this rule.

```sql
ALTER TABLE coin_state 
ADD COLUMN IF NOT EXISTS tp0_hit BOOLEAN DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS tp0_price NUMERIC,
ADD COLUMN IF NOT EXISTS tp0_fired_at TIMESTAMPTZ;
```

---

## 2026-06-27

### Fixed — Critical: L2 re-entry blocked on 194 coins
**Problem:** Coins with closed positions never received new L2 alerts, regardless of how strong the new signal was.

**Root cause:** `if is_l2 and not l2_fired:` prevented `l2_fired_at` from resetting once a position closed. The alert loop's 30-minute age check then saw a stale (sometimes 30+ day old) timestamp and silently skipped the alert — at both signal-processing locations in `main.py` (~line 1521 and ~line 1684).

**Fix:** Added `position_was_closed` check (`position_closed`, `time_stop_hit`, or `sl_hit`) and updated the condition to `if is_l2 and (not l2_fired or position_was_closed):` in both locations — allowing `l2_fired_at` to reset to `now` on legitimate re-entries.

**Impact:** Unlocked re-entry alerts on 194 previously permanently-blocked coins.

### Infrastructure — Public Telegram channel launched
Migrated alerts from personal Telegram chat to a public channel: `t.me/MomentumAlphaSignals` (channel ID `-1003770106536`). Bot `@Wop_momentum_v2_bot` added as channel admin. `TELEGRAM_CHAT_ID` environment variable updated in Railway.

### Infrastructure — GitHub repository made public
Created `github.com/nicopxm/momentum-tracker` (public), added `.gitignore` (env vars, venv, `.claude/` excluded from initial setup, later re-included for the skill), wrote comprehensive `README.md` covering architecture, signal pipeline, exit system, and live performance.

### Infrastructure — Streamlit Cloud redeploy
Resolved a stale deployment pointing to the old V1 dashboard file. Deleted and recreated the Streamlit Cloud app pointing to `nicopxm/momentum-tracker`, branch `main`, main file `dashboard_v2.py`. Live at `momentum-tracker-mirjjfgreydqj26dgyswz7.streamlit.app`.

---

## 2026-06-26

### Fixed — Hall of Fame data integrity
- Removed duplicate entries (O-USD, SYND-USD, UP-USD each appeared twice from manual seeding + auto-insert overlap)
- Deleted AAVE-USD entry — was inserted with `exit_gain` despite the position still being open (`tp2_hit = false`)
- Deleted G-USD `DUMP_EXIT` entry — `exit_gain` (+11.7%) was mathematically greater than `peak_gain` (+7.7%), indicating corrupted seed data

### Fixed — Dashboard Hall of Fame sort order and display
Sort changed from `recorded_at DESC` (all identical seed timestamps) to `l2_fired_at DESC` (actual trade date). Removed "left on table" metric (averaged ~+24% across all exit types, not differentiating, and produced confusing negative-looking values like BICO's -173.4%). Added RSI and RS/BTC display per card.

### Added — Best Open KPI card
New dashboard card showing the highest-gaining currently open position, filling dead space in the row 1 KPI layout between Last Scan and BTC Price.

---

## 2026-06-15 to 2026-06-25 (V2 stabilization window)

### Fixed — TA indicators never persisting to Supabase
**Problem:** RSI, MACD, and EMA columns were NULL for all 231 coins despite being calculated every cycle.

**Root cause:** Indicator writes were placed inside the `except` block of `update_coin_state` — which never executed because the `try` block always succeeded.

**Fix:** Moved indicator writes into both the UPDATE and INSERT branches inside the `try` block.

### Fixed — peak_price updating on closed positions
**Problem:** `peak_price` continued updating after a position closed, producing phantom gains weeks after the actual exit and corrupting Hall of Fame data.

**Fix:** Added freeze condition — `peak_price` no longer updates when `position_closed`, `time_stop_hit`, or `sl_hit` is `True`.

### Fixed — NaN propagation in RSI and RS/BTC
Added `pd.isna()` guards at calculation time and at all write locations for both `rsi` and `rs_vs_btc` to prevent `NaN` from being written to Supabase or crashing downstream calculations.

### Added — Hall of Fame auto-insert
Three triggers added inside `check_tp_sl`: `tp2_hit` (TP1_TRAIL), `time_stop_hit` with gain ≥5% (TIME_STOP), and `dump_fired` with gain ≥5% (DUMP_EXIT). All wrapped in try/except to avoid disrupting core trading logic on insert failure.

### Egress — Architecture overhaul (16GB → 2.5GB/month)
- Batch `state_cache` — one SELECT for all 231 coins per cycle replacing per-coin queries
- Pump alert loop converted from per-coin SELECT to `state_cache.get()`
- Conditional `momentum_history` writes — only active coins
- Candle fetch reduced from 350 to 250 per coin
- Summary queries (`send_15min_summary`, `send_1hour_summary`) switched to explicit column lists

### Added — RS/BTC market-beta suppression
L2 alerts suppressed when `BTC_CHANGE_24HR >= 3.0` and the coin's `rs_vs_btc < 5.0` — prevents mass false alerts when the whole market pumps together rather than coin-specific demand.

### Fixed — Intra-cycle TP1 detection
Originally checked only the latest poll price for TP1 (+20%). Added `df["close"].iloc[-8:].max()` (later widened to `-15:` on 2026-06-29) to catch fast intra-cycle spikes that retrace before the next 7-minute poll.

### Fixed — Peak-based hard stop
Coins that reached +20% or more peak gain now use a -15%-from-peak stop instead of the standard -8%-from-entry stop, protecting more of an already-confirmed move.

---

## 2026-05-24 — V2 Launch

- Initial production deployment of Momentum V2 on Railway
- 231 Coinbase USD pairs scanned every 7 minutes across 4 timeframes
- L1/L2 signal detection with volume confirmation (1.5x–3.0x threshold)
- Dynamic L2 early detection with 5 safeguards for high-momentum coins
- HH/HL multi-leg pattern detection from daily snapshots
- Slow Grinder three-tier detection (Fast/Mid/Slow)
- RSI-14, MACD 12/26/9, EMA 20/50, RS/BTC indicators
- Automated TP/SL position management: TP1 (+20%), trailing stop (-12% from peak), dynamic hard stop (-8%/-12%), breakeven trigger, weak signal exit (2hr)
- Unified Momentum Score (0–100) combining all signal layers
- Streamlit dashboard with 8 sections: Active Movers, Signal Feed, Coin Detail, Leaderboard, Hall of Fame, About, How It Works, Contact
- Supabase (PostgreSQL) backend, Telegram alert integration

---

## Performance Snapshot

| Date | TP1 Rate | Avg Trail Exit | Hall of Fame Wins | Notes |
|---|---|---|---|---|
| 2026-06-30 | 5.3% | +37.7% | 26 | TP0 tier deployed |
| 2026-06-26 | 8.1% | +43.0% | 26 (post-cleanup) | Duplicate/bad data removed |
| 2026-06-15 | 13.8% | — | — | Post re-entry-fix snapshot |
| 2026-05-24 → 06-14 | 3.4% (pre-fix) | — | — | Baseline, V2 launch window |

**Target:** 24% TP1 rate to break even at current 3.17:1 risk/reward ratio. 30%+ for sustained profitability.