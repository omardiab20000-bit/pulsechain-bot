import re
import time
import html
from datetime import datetime, timezone
from urllib.parse import quote_plus
from xml.etree import ElementTree as ET

import httpx

# =========================================================
# CONFIG
# =========================================================
DISCORD_WEBHOOK = "https://discord.com/api/webhooks/1483880814537216100/gM_wVR-G6zJrh05I30pkkVDLQ9YH-alYSWLR-f-4-MITMx7YR4RiVX-1qrSaN2sWM9or"

DEBUG = False
POLL_SECONDS = 300

TOKEN_ALERT_COOLDOWN_SECONDS = 60 * 45
MACRO_ALERT_COOLDOWN_SECONDS = 60 * 45
NEWS_ALERT_COOLDOWN_SECONDS = 60 * 90

QUIET_HOURS_BETWEEN_SAME_NEWS = 6
MIN_NEWS_SCORE = 5
MIN_NEWS_PRICE_MOVE_FOR_ALERT = 1.25

client = httpx.Client(
    timeout=20.0,
    follow_redirects=True,
    headers={
        "User-Agent": "Mozilla/5.0 PulseChainRotationAgent/2.0"
    }
)

# =========================================================
# STATE
# =========================================================
last_richard_status = None
last_richard_daily_date = None
last_market_insight_date = None

last_btc_eth_signals = {"bitcoin": None, "ethereum": None}
last_macro_alert_time = {"bitcoin": 0, "ethereum": 0}

last_token_signals = {"PLS": None, "PLSX": None, "PROVEX": None}
last_token_alert_time = {"PLS": 0, "PLSX": 0, "PROVEX": 0}
last_token_states = {"PLS": "neutral", "PLSX": "neutral", "PROVEX": "neutral"}

last_news_alert_time = 0
seen_news_titles = {}   # normalized_title -> unix ts
seen_news_groups = {}   # normalized_group -> unix ts

market_cache = {
    "macro_bias": "neutral",
    "btc_1h": 0.0,
    "btc_24h": 0.0,
    "eth_1h": 0.0,
    "eth_24h": 0.0,
    "btc_price": 0.0,
    "eth_price": 0.0,
    "btc_vol": 0.0,
    "eth_vol": 0.0,
    "updated_at": 0.0,
}

# =========================================================
# TOKENS
# =========================================================
TOKENS = [
    {"symbol": "PLS", "search": "PLS pulsechain", "label": "🟢 PLS"},
    {"symbol": "PLSX", "search": "PLSX pulsechain", "label": "🟣 PLSX"},
    {"symbol": "PROVEX", "search": "PROVEX pulsechain", "label": "🧪 PROVEX Coin"},
]

# =========================================================
# HELPERS
# =========================================================
def log(*args):
    if DEBUG:
        print("[DEBUG]", *args, flush=True)

def now_utc():
    return datetime.now(timezone.utc)

def utc_stamp():
    return now_utc().strftime("%Y-%m-%d %H:%M UTC")

def safe_float(v, default=0.0):
    try:
        return float(v or 0)
    except Exception:
        return default

def fmt_pct(v):
    v = safe_float(v)
    sign = "+" if v > 0 else ""
    return f"{sign}{v:.2f}%"

def fmt_money(v):
    v = safe_float(v)
    if v >= 1_000_000_000:
        return f"${v/1_000_000_000:.2f}B"
    if v >= 1_000_000:
        return f"${v/1_000_000:.2f}M"
    if v >= 1_000:
        return f"${v/1_000:.2f}K"
    return f"${v:.2f}"

def fmt_ratio(v):
    return f"{safe_float(v):.2f}x"

def clamp(v, lo, hi):
    return max(lo, min(hi, v))

def can_send_again(last_sent_ts, cooldown_seconds):
    return (time.time() - float(last_sent_ts or 0)) >= cooldown_seconds

def normalize_text(s):
    s = html.unescape(s or "")
    s = s.lower().strip()
    s = re.sub(r"https?://\S+", "", s)
    s = re.sub(r"[^a-z0-9\s]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def strip_source_suffix(title):
    t = title or ""
    # remove common source suffix patterns
    t = re.sub(r"\s*[-–|]\s*[^-–|]{1,40}$", "", t).strip()
    return t

def normalized_title_key(title):
    return normalize_text(strip_source_suffix(title))

def normalized_group_key(text):
    text = normalize_text(text)
    # collapse similar event phrases
    replacements = [
        ("federal reserve", "fed"),
        ("u s ", "us "),
        ("sec ", "sec "),
        ("exchange traded fund", "etf"),
        ("ethereum etf", "eth etf"),
        ("bitcoin etf", "btc etf"),
        ("bank collapse", "bank stress"),
        ("bank failure", "bank stress"),
        ("hack", "security breach"),
        ("exploit", "security breach"),
    ]
    for a, b in replacements:
        text = text.replace(a, b)
    return text[:140]

def cleanup_seen_news():
    now_ts = time.time()
    stale_after = 60 * 60 * 24 * 2
    for d in (seen_news_titles, seen_news_groups):
        old_keys = [k for k, ts in d.items() if (now_ts - ts) > stale_after]
        for k in old_keys:
            d.pop(k, None)

def send_embed(title, description, color=0x8E44AD, url=None):
    embed = {
        "title": title,
        "description": description,
        "color": color,
        "footer": {"text": f"PulseChain Rotation Agent • {utc_stamp()}"},
    }
    if url:
        embed["url"] = url

    payload = {"embeds": [embed]}
    try:
        r = client.post(DISCORD_WEBHOOK, json=payload)
        r.raise_for_status()
    except Exception as e:
        print("Webhook embed error:", e, flush=True)

# =========================================================
# DISCORD COLORS / LABELS
# =========================================================
SEVERITY_COLOR = {
    "watch": 0xF1C40F,
    "strong": 0x2ECC71,
    "urgent": 0xE74C3C,
    "risk": 0xC0392B,
    "info": 0x3498DB,
    "macro": 0x5865F2,
}

STATE_ICON = {
    "neutral": "⚪",
    "buildup": "🟡",
    "strong": "🟢",
    "breakout": "🚀",
    "dip_buy": "🛒",
    "risk": "🔴",
    "flush": "💥",
}

# =========================================================
# DEXSCREENER
# =========================================================
def fetch_token_market(search_term):
    try:
        url = "https://api.dexscreener.com/latest/dex/search"
        r = client.get(url, params={"q": search_term})
        r.raise_for_status()
        data = r.json()
        pairs = data.get("pairs", [])

        if not pairs:
            return None

        pulse_pairs = [p for p in pairs if (p.get("chainId") or "").lower() == "pulsechain"]
        if pulse_pairs:
            pairs = pulse_pairs

        def score(p):
            liq = safe_float((p.get("liquidity") or {}).get("usd"))
            vol_h24 = safe_float((p.get("volume") or {}).get("h24"))
            tx_h1 = (p.get("txns") or {}).get("h1") or {}
            buys = safe_float(tx_h1.get("buys"))
            sells = safe_float(tx_h1.get("sells"))

            # prefer real, tradable pairs
            pair_score = 0.0
            pair_score += liq * 0.58
            pair_score += vol_h24 * 0.34
            pair_score += (buys + sells) * 45

            # penalty for extremely weak pairs
            if liq < 25_000:
                pair_score *= 0.65
            if vol_h24 < 15_000:
                pair_score *= 0.78

            return pair_score

        best = sorted(pairs, key=score, reverse=True)[0]

        txns_h1 = (best.get("txns") or {}).get("h1") or {}
        txns_h24 = (best.get("txns") or {}).get("h24") or {}
        liquidity = best.get("liquidity") or {}
        volume = best.get("volume") or {}
        price_change = best.get("priceChange") or {}

        buys_h1 = safe_float(txns_h1.get("buys"))
        sells_h1 = safe_float(txns_h1.get("sells"))
        buys_h24 = safe_float(txns_h24.get("buys"))
        sells_h24 = safe_float(txns_h24.get("sells"))

        ratio_h1 = buys_h1 / max(1.0, sells_h1)
        ratio_h24 = buys_h24 / max(1.0, sells_h24)

        liq_usd = safe_float(liquidity.get("usd"))
        vol_h1 = safe_float(volume.get("h1"))
        vol_h6 = safe_float(volume.get("h6"))
        vol_h24 = safe_float(volume.get("h24"))

        h1_change = safe_float(price_change.get("h1"))
        h6_change = safe_float(price_change.get("h6"))
        h24_change = safe_float(price_change.get("h24"))

        volume_to_liquidity = vol_h1 / max(liq_usd, 1.0)
        volume_spike_score = clamp((volume_to_liquidity / 0.05) * 2.2, 0, 3.0)

        absorption_score = 0.0
        if h1_change < 0 and ratio_h1 >= 1.2:
            absorption_score += 1.5
        if h6_change < 0 and ratio_h24 >= 1.05:
            absorption_score += 1.0

        trend_score = 0.0
        if h1_change > 0:
            trend_score += 0.8
        if h6_change > 0:
            trend_score += 1.0
        if h24_change > 0:
            trend_score += 0.8

        pressure_score = clamp(min(4.0, ratio_h1) * 1.55, 0, 6.2)

        liquidity_quality = 0.0
        if liq_usd >= 1_000_000:
            liquidity_quality = 2.0
        elif liq_usd >= 250_000:
            liquidity_quality = 1.4
        elif liq_usd >= 75_000:
            liquidity_quality = 0.9
        elif liq_usd >= 25_000:
            liquidity_quality = 0.45

        flow_score = pressure_score + volume_spike_score + absorption_score + trend_score + liquidity_quality
        flow_score = clamp(flow_score, 0, 10)

        fake_pump_risk = 0.0
        if h1_change > 8 and ratio_h1 < 1.05:
            fake_pump_risk += 2.5
        if liq_usd < 50_000 and h1_change > 5:
            fake_pump_risk += 2.0
        if vol_h1 < 5_000 and h1_change > 4:
            fake_pump_risk += 1.0

        confidence = flow_score
        confidence += 0.6 if liq_usd >= 100_000 else 0.0
        confidence += 0.5 if ratio_h1 >= 1.25 else 0.0
        confidence -= fake_pump_risk
        confidence = clamp(confidence, 1, 10)

        return {
            "symbol": best.get("baseToken", {}).get("symbol") or search_term.split()[0],
            "pair_address": best.get("pairAddress") or "",
            "dex_id": best.get("dexId") or "",
            "url": best.get("url") or "",
            "liq_usd": liq_usd,
            "vol_h1": vol_h1,
            "vol_h6": vol_h6,
            "vol_h24": vol_h24,
            "buys_h1": buys_h1,
            "sells_h1": sells_h1,
            "buys_h24": buys_h24,
            "sells_h24": sells_h24,
            "ratio_h1": ratio_h1,
            "ratio_h24": ratio_h24,
            "h1_change": h1_change,
            "h6_change": h6_change,
            "h24_change": h24_change,
            "vol_liq_ratio_h1": volume_to_liquidity,
            "flow_score": flow_score,
            "confidence": confidence,
            "fake_pump_risk": fake_pump_risk,
        }

    except Exception as e:
        print("Dex fetch error:", search_term, e, flush=True)
        return None

# =========================================================
# MACRO
# =========================================================
def refresh_macro_market():
    global market_cache
    try:
        url = "https://api.coingecko.com/api/v3/coins/markets"
        params = {
            "vs_currency": "usd",
            "ids": "bitcoin,ethereum",
            "price_change_percentage": "1h,24h"
        }
        r = client.get(url, params=params)
        r.raise_for_status()
        data = r.json()

        coin_map = {c["id"]: c for c in data}
        btc = coin_map.get("bitcoin")
        eth = coin_map.get("ethereum")

        if not btc or not eth:
            return

        btc_1h = safe_float(btc.get("price_change_percentage_1h_in_currency"))
        btc_24h = safe_float(btc.get("price_change_percentage_24h"))
        eth_1h = safe_float(eth.get("price_change_percentage_1h_in_currency"))
        eth_24h = safe_float(eth.get("price_change_percentage_24h"))

        avg = (btc_24h + eth_24h) / 2.0

        bias = "neutral"
        if avg >= 2.2:
            bias = "bullish"
        elif avg <= -2.2:
            bias = "bearish"

        market_cache.update({
            "macro_bias": bias,
            "btc_1h": btc_1h,
            "btc_24h": btc_24h,
            "eth_1h": eth_1h,
            "eth_24h": eth_24h,
            "btc_price": safe_float(btc.get("current_price")),
            "eth_price": safe_float(eth.get("current_price")),
            "btc_vol": safe_float(btc.get("total_volume")),
            "eth_vol": safe_float(eth.get("total_volume")),
            "updated_at": time.time(),
        })
    except Exception as e:
        print("Macro refresh error:", e, flush=True)

def macro_alignment_bonus(token_market):
    bias = market_cache.get("macro_bias", "neutral")
    h1 = token_market["h1_change"]
    h6 = token_market["h6_change"]

    bonus = 0.0
    if bias == "bullish" and (h1 > 0 or h6 > 0):
        bonus += 0.8
    elif bias == "bearish" and (h1 < 0 or h6 < 0):
        bonus += 0.4
    elif bias == "bearish" and (h1 > 0 and h6 > 0):
        bonus -= 0.7

    return bonus

# =========================================================
# TOKEN SIGNAL ENGINE
# =========================================================
def derive_token_state(m):
    ratio = m["ratio_h1"]
    flow = m["flow_score"]
    h1 = m["h1_change"]
    h6 = m["h6_change"]
    conf = m["confidence"]
    fake_risk = m["fake_pump_risk"]

    if (h1 <= -8 or h6 <= -15) and ratio >= 1.35 and flow >= 6.2:
        return "dip_buy", "urgent", "Heavy dip with real buying absorption", "شراء الآن"

    if h1 <= -8 and ratio < 1.0 and conf < 5:
        return "flush", "risk", "Sharp downside with weak support", "لا دخول — انتبه"

    if flow >= 7.4 and ratio >= 1.30 and h1 >= -2:
        if h1 >= 2 or h6 >= 5:
            return "breakout", "urgent", "Momentum breakout with real flow", "راقب الاختراق — لا تطارد بعنف"
        return "strong", "strong", "Clear liquidity and buying strength", "عزّز بشكل تدريجي"

    if flow >= 5.8 and ratio >= 1.12:
        return "buildup", "watch", "Activity is building under the surface", "راقب — دخول تدريجي"

    if h1 <= -6 or h6 <= -10:
        if ratio >= 1.05:
            return "buildup", "watch", "Drop is being absorbed by buyers", "راقب الارتداد — لا تستعجل"
        return "risk", "risk", "Sell pressure is stronger than demand", "خليك كاش — خطر"

    if fake_risk >= 2.5:
        return "risk", "risk", "Move looks overheated or low-quality", "لا تطارد — انتظر تأكيد"

    return "neutral", "info", "Neutral market with no clear edge", "خليك كاش — انتظار"

def build_token_signal(symbol, label, m):
    state, severity, market_read, action_ar = derive_token_state(m)

    confidence = clamp(m["confidence"] + macro_alignment_bonus(m), 1, 10)

    reasons = []
    if m["ratio_h1"] >= 1.2:
        reasons.append("buyers > sellers")
    if m["vol_liq_ratio_h1"] >= 0.04:
        reasons.append("real flow vs liquidity")
    if m["h1_change"] < 0 and m["ratio_h1"] >= 1.1:
        reasons.append("dip absorption")
    if m["h1_change"] > 0 and m["h6_change"] > 0:
        reasons.append("trend confirmation")
    if market_cache.get("macro_bias") == "bullish":
        reasons.append("macro tailwind")
    elif market_cache.get("macro_bias") == "bearish" and state in ("risk", "flush"):
        reasons.append("macro pressure")

    if not reasons:
        reasons.append("market structure not clean")

    why_line = ", ".join(reasons[:3])

    desc = (
        f"**Market Read:** {market_read}\n"
        f"**State:** {state.title()}\n"
        f"**Severity:** {severity.title()}\n"
        f"**Confidence:** {confidence:.1f}/10\n"
        f"**Liquidity Flow:** {m['flow_score']:.1f}/10\n"
        f"**Buy/Sell Ratio:** {fmt_ratio(m['ratio_h1'])}\n"
        f"**1H Change:** {fmt_pct(m['h1_change'])}\n"
        f"**6H Change:** {fmt_pct(m['h6_change'])}\n"
        f"**1H Volume:** {fmt_money(m['vol_h1'])}\n"
        f"**Liquidity:** {fmt_money(m['liq_usd'])}\n"
        f"**Why Now:** {why_line}\n\n"
        f"👉 **Take Action:** {action_ar}"
    )

    title = f"{STATE_ICON.get(state, '⚪')} {label}"
    color = SEVERITY_COLOR.get(severity, 0x8E44AD)
    return state, severity, confidence, title, desc, color

def should_send_token_alert(symbol, state, severity, confidence, current_signal):
    previous_state = last_token_states.get(symbol, "neutral")
    previous_signal = last_token_signals.get(symbol)
    cooldown_ok = can_send_again(last_token_alert_time.get(symbol), TOKEN_ALERT_COOLDOWN_SECONDS)

    state_changed = state != previous_state
    signal_changed = current_signal != previous_signal

    if state in ("neutral",):
        return False

    # always send urgent state transitions
    if state_changed and severity in ("urgent", "risk"):
        return True

    # strong signals can send if changed enough
    if signal_changed and confidence >= 7.0 and cooldown_ok:
        return True

    # watch signals only if state changed out of neutral/risk
    if state_changed and severity == "watch" and previous_state in ("neutral", "risk", "flush"):
        return True

    return False

def monitor_tokens():
    global last_token_signals, last_token_alert_time, last_token_states

    for token in TOKENS:
        market = fetch_token_market(token["search"])
        log(token["symbol"], "market =", market)

        if not market:
            continue

        symbol = token["symbol"]
        label = token["label"]

        state, severity, confidence, title, desc, color = build_token_signal(symbol, label, market)

        current_signal = (
            f"{state}|{severity}|"
            f"{round(market['h1_change'],1)}|"
            f"{round(market['h6_change'],1)}|"
            f"{round(market['ratio_h1'],2)}|"
            f"{round(market['flow_score'],1)}|"
            f"{round(confidence,1)}"
        )

        if should_send_token_alert(symbol, state, severity, confidence, current_signal):
            send_embed(title, desc, color, url=market.get("url") or None)
            last_token_alert_time[symbol] = time.time()

        last_token_signals[symbol] = current_signal
        last_token_states[symbol] = state

# =========================================================
# RICHARD HEART
# =========================================================
def monitor_richard_heart():
    global last_richard_status
    try:
        r = client.get("https://richardheart.com/")
        online = 200 <= r.status_code < 400
    except Exception:
        online = False

    if last_richard_status is None:
        last_richard_status = online
        return

    if online != last_richard_status:
        if online:
            send_embed(
                "🟢 RichardHeart.com",
                "**Status:** Online\n**Why Now:** status changed from offline to online\n\n👉 **Take Action:** راقب لاحتمال عودة النشاط أو بث",
                SEVERITY_COLOR["strong"],
                url="https://richardheart.com/"
            )
        else:
            send_embed(
                "🔴 RichardHeart.com",
                "**Status:** Offline\n**Why Now:** status changed from online to offline\n\n👉 **Take Action:** لا تغيير حالياً",
                SEVERITY_COLOR["risk"],
                url="https://richardheart.com/"
            )
        last_richard_status = online

def daily_richard_heart_update():
    global last_richard_daily_date
    today = now_utc().date()

    if last_richard_daily_date == today:
        return

    try:
        r = client.get("https://richardheart.com/")
        online = 200 <= r.status_code < 400
    except Exception:
        online = False

    if online:
        send_embed(
            "🟢 RichardHeart.com — Daily Update",
            "**Status:** Online\n\n👉 **Take Action:** راقب لأي نشاط أو بث",
            SEVERITY_COLOR["strong"],
            url="https://richardheart.com/"
        )
    else:
        send_embed(
            "🔴 RichardHeart.com — Daily Update",
            "**Status:** Offline\n\n👉 **Take Action:** لا تغيير اليوم",
            SEVERITY_COLOR["risk"],
            url="https://richardheart.com/"
        )

    last_richard_daily_date = today

# =========================================================
# BTC / ETH ALERTS
# =========================================================
def monitor_btc_eth():
    global last_btc_eth_signals, last_macro_alert_time

    try:
        if (time.time() - market_cache.get("updated_at", 0)) > 120:
            refresh_macro_market()

        for coin_id, label in [("bitcoin", "₿ Bitcoin"), ("ethereum", "⟠ Ethereum")]:
            if coin_id == "bitcoin":
                ch1 = market_cache["btc_1h"]
                ch24 = market_cache["btc_24h"]
            else:
                ch1 = market_cache["eth_1h"]
                ch24 = market_cache["eth_24h"]

            signal = None
            severity = "info"
            market_read = None
            action_ar = None
            color = SEVERITY_COLOR["macro"]

            if ch1 >= 3.0 or ch24 >= 5.0:
                signal = "up"
                severity = "urgent" if (ch1 >= 4.2 or ch24 >= 7.0) else "strong"
                market_read = "Strong upside move"
                action_ar = "راقب الزخم — لا تطارد"
                color = SEVERITY_COLOR["strong"] if severity == "strong" else SEVERITY_COLOR["urgent"]

            elif ch1 <= -3.0 or ch24 <= -5.0:
                signal = "down"
                severity = "urgent" if (ch1 <= -4.2 or ch24 <= -7.0) else "watch"
                market_read = "Clear downside pressure"
                action_ar = "راقب الدعم — لا تستعجل"
                color = SEVERITY_COLOR["risk"] if severity == "urgent" else 0xE67E22

            if not signal:
                continue

            same_signal = last_btc_eth_signals.get(coin_id) == signal
            cooldown_ok = can_send_again(last_macro_alert_time.get(coin_id), MACRO_ALERT_COOLDOWN_SECONDS)

            if same_signal and not cooldown_ok:
                continue

            desc = (
                f"**Market Read:** {market_read}\n"
                f"**Severity:** {severity.title()}\n"
                f"**1H Change:** {fmt_pct(ch1)}\n"
                f"**24H Change:** {fmt_pct(ch24)}\n"
                f"**Macro Bias:** {market_cache.get('macro_bias', 'neutral').title()}\n\n"
                f"👉 **Take Action:** {action_ar}"
            )

            title_icon = "🚨" if signal == "up" else "🔻"
            send_embed(f"{title_icon} {label}", desc, color)

            last_btc_eth_signals[coin_id] = signal
            last_macro_alert_time[coin_id] = time.time()

    except Exception as e:
        print("BTC/ETH error:", e, flush=True)

# =========================================================
# DAILY MARKET INSIGHT
# =========================================================
def daily_market_insight():
    global last_market_insight_date
    today = now_utc().date()

    if last_market_insight_date == today:
        return

    try:
        if (time.time() - market_cache.get("updated_at", 0)) > 120:
            refresh_macro_market()

        btc_24 = market_cache["btc_24h"]
        eth_24 = market_cache["eth_24h"]
        avg = (btc_24 + eth_24) / 2.0

        if avg > 2:
            state = "Bullish"
            action = "راقب — دخول تدريجي"
            color = SEVERITY_COLOR["strong"]
        elif avg < -2:
            state = "Bearish"
            action = "خليك كاش — انتظار"
            color = SEVERITY_COLOR["risk"]
        else:
            state = "Neutral"
            action = "مراقبة فقط"
            color = SEVERITY_COLOR["info"]

        send_embed(
            "📊 Market Insight",
            f"**Today:** {state}\n"
            f"**₿ BTC 24H:** {fmt_pct(btc_24)}\n"
            f"**⟠ ETH 24H:** {fmt_pct(eth_24)}\n"
            f"**Macro Bias:** {market_cache.get('macro_bias', 'neutral').title()}\n\n"
            f"👉 **Take Action:** {action}",
            color
        )

        last_market_insight_date = today

    except Exception as e:
        print("Insight error:", e, flush=True)

# =========================================================
# NEWS ENGINE
# =========================================================
NEWS_FEEDS = [
    {
        "name": "Google News BTC",
        "url": "https://news.google.com/rss/search?q=" + quote_plus("Bitcoin OR BTC when:1d") + "&hl=en-US&gl=US&ceid=US:en"
    },
    {
        "name": "Google News ETH",
        "url": "https://news.google.com/rss/search?q=" + quote_plus("Ethereum OR ETH when:1d") + "&hl=en-US&gl=US&ceid=US:en"
    },
    {
        "name": "Google News Crypto Macro",
        "url": "https://news.google.com/rss/search?q=" + quote_plus("crypto bank collapse fed sec etf exchange hack when:1d") + "&hl=en-US&gl=US&ceid=US:en"
    },
]

BULLISH_KEYWORDS = {
    "approval": 2, "approved": 2, "adoption": 2, "surge": 2, "rally": 2, "buy": 1,
    "inflow": 2, "breakout": 2, "institutional": 1, "treasury": 1, "launch": 1,
    "record high": 2, "all time high": 3, "etf": 1
}

BEARISH_KEYWORDS = {
    "hack": 3, "breach": 3, "exploit": 3, "collapse": 3, "bankruptcy": 3, "liquidation": 2,
    "ban": 3, "lawsuit": 2, "sec": 1, "dump": 2, "selloff": 2, "crash": 3, "recession": 2,
    "fed": 1, "war": 2, "tariff": 2, "default": 3, "outflow": 2
}

BTC_CONTEXT = {"bitcoin", "btc", "microstrategy", "strategy", "etf"}
ETH_CONTEXT = {"ethereum", "eth", "ether", "staking", "spot etf"}
CRYPTO_CONTEXT = {"crypto", "exchange", "binance", "coinbase", "stablecoin", "market"}

def fetch_rss_items(url):
    try:
        r = client.get(url)
        r.raise_for_status()
        root = ET.fromstring(r.text)

        items = []
        for item in root.findall(".//item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            pub_date = (item.findtext("pubDate") or "").strip()
            if title and link:
                items.append({
                    "title": title,
                    "link": link,
                    "pubDate": pub_date,
                })
        return items
    except Exception as e:
        print("RSS fetch error:", e, flush=True)
        return []

def headline_score_and_direction(title):
    t = normalize_text(title)
    bull = 0
    bear = 0

    for kw, score in BULLISH_KEYWORDS.items():
        if kw in t:
            bull += score

    for kw, score in BEARISH_KEYWORDS.items():
        if kw in t:
            bear += score

    context = []
    if any(k in t for k in BTC_CONTEXT):
        context.append("bitcoin")
    if any(k in t for k in ETH_CONTEXT):
        context.append("ethereum")
    if any(k in t for k in CRYPTO_CONTEXT):
        context.append("crypto")

    total = max(bull, bear)
    direction = "neutral"
    if bull > bear:
        direction = "bullish"
    elif bear > bull:
        direction = "bearish"

    # market-moving boost
    if "etf" in t:
        total += 1
    if "hack" in t or "collapse" in t or "bankruptcy" in t:
        total += 2
    if "fed" in t or "sec" in t:
        total += 1

    return total, direction, context

def explain_news_impact(direction, context):
    macro = market_cache.get("macro_bias", "neutral")
    btc_24 = market_cache.get("btc_24h", 0.0)
    eth_24 = market_cache.get("eth_24h", 0.0)

    if direction == "bearish":
        if abs(btc_24) >= MIN_NEWS_PRICE_MOVE_FOR_ALERT or abs(eth_24) >= MIN_NEWS_PRICE_MOVE_FOR_ALERT:
            return "Headline aligns with current risk-off price action"
        return "Negative headline, but price confirmation is still limited"

    if direction == "bullish":
        if btc_24 >= MIN_NEWS_PRICE_MOVE_FOR_ALERT or eth_24 >= MIN_NEWS_PRICE_MOVE_FOR_ALERT:
            return "Headline supports current upside momentum"
        return "Positive headline, but market has not fully confirmed yet"

    if macro != "neutral":
        return f"Macro bias is {macro}, keep position sizing disciplined"
    return "This may matter if price starts reacting"

def action_from_news(direction, context):
    if direction == "bearish":
        return "خفف الاندفاع — راقب السيولة والدعم"
    if direction == "bullish":
        return "راقب الزخم — لا تطارد بدون تأكيد"
    return "مراقبة فقط"

def news_is_relevant(total_score, direction, context):
    if total_score < MIN_NEWS_SCORE:
        return False

    if direction == "neutral":
        return False

    # must be crypto-relevant
    if not context:
        return False

    # confirm with price action OR very strong headline
    btc_move = abs(market_cache.get("btc_24h", 0.0))
    eth_move = abs(market_cache.get("eth_24h", 0.0))
    if total_score >= 7:
        return True
    if btc_move >= MIN_NEWS_PRICE_MOVE_FOR_ALERT or eth_move >= MIN_NEWS_PRICE_MOVE_FOR_ALERT:
        return True

    return False

def dedupe_news_items(items):
    unique = []
    local_seen = set()

    for item in items:
        key = normalized_title_key(item["title"])
        if not key or key in local_seen:
            continue
        local_seen.add(key)
        unique.append(item)

    return unique

def collect_news_candidates():
    items = []
    for feed in NEWS_FEEDS:
        items.extend(fetch_rss_items(feed["url"]))
    return dedupe_news_items(items)

def pick_best_news_event():
    cleanup_seen_news()
    candidates = collect_news_candidates()

    scored = []
    for item in candidates:
        title = item["title"]
        key = normalized_title_key(title)

        total_score, direction, context = headline_score_and_direction(title)
        if not news_is_relevant(total_score, direction, context):
            continue

        group_key = normalized_group_key(title)

        # avoid repeated same title/group
        if key in seen_news_titles:
            continue
        if group_key in seen_news_groups and (time.time() - seen_news_groups[group_key]) < (QUIET_HOURS_BETWEEN_SAME_NEWS * 3600):
            continue

        score = total_score
        # boost if direction aligns with price move
        if direction == "bullish" and (market_cache.get("btc_24h", 0) > 0 or market_cache.get("eth_24h", 0) > 0):
            score += 1
        if direction == "bearish" and (market_cache.get("btc_24h", 0) < 0 or market_cache.get("eth_24h", 0) < 0):
            score += 1

        scored.append((score, item, direction, context, group_key, key))

    if not scored:
        return None

    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0]

def monitor_major_news():
    global last_news_alert_time

    try:
        if not can_send_again(last_news_alert_time, NEWS_ALERT_COOLDOWN_SECONDS):
            return

        if (time.time() - market_cache.get("updated_at", 0)) > 120:
            refresh_macro_market()

        best = pick_best_news_event()
        if not best:
            return

        score, item, direction, context, group_key, key = best
        title = strip_source_suffix(item["title"])
        impact = explain_news_impact(direction, context)
        action = action_from_news(direction, context)

        severity = "strong"
        color = SEVERITY_COLOR["macro"]
        icon = "📰"

        if direction == "bearish":
            icon = "🚨"
            color = SEVERITY_COLOR["risk"] if score >= 7 else 0xE67E22
            severity = "urgent" if score >= 7 else "watch"
        elif direction == "bullish":
            icon = "🟢"
            color = SEVERITY_COLOR["strong"] if score >= 7 else 0x27AE60
            severity = "urgent" if score >= 7 else "strong"

        context_label = ", ".join(sorted(set(context))).title() if context else "Crypto"

        desc = (
            f"**Headline:** {title}\n"
            f"**Direction:** {direction.title()}\n"
            f"**Severity:** {severity.title()}\n"
            f"**News Score:** {score}/10\n"
            f"**Context:** {context_label}\n"
            f"**Market Impact:** {impact}\n"
            f"**₿ BTC 24H:** {fmt_pct(market_cache.get('btc_24h', 0))}\n"
            f"**⟠ ETH 24H:** {fmt_pct(market_cache.get('eth_24h', 0))}\n\n"
            f"👉 **Take Action:** {action}"
        )

        send_embed(f"{icon} Major Market News", desc, color, url=item["link"])

        seen_news_titles[key] = time.time()
        seen_news_groups[group_key] = time.time()
        last_news_alert_time = time.time()

    except Exception as e:
        print("News monitor error:", e, flush=True)

# =========================================================
# MAIN LOOP
# =========================================================
def run_bot():
    print("PulseChain Rotation Agent PRO started...", flush=True)
    while True:
        try:
            refresh_macro_market()
            monitor_tokens()
            monitor_richard_heart()
            daily_richard_heart_update()
            monitor_btc_eth()
            daily_market_insight()
            monitor_major_news()
        except Exception as e:
            print("Main loop error:", e, flush=True)

        time.sleep(POLL_SECONDS)
