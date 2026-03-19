import os
import time
import httpx
from collections import defaultdict, deque

DEX_URL = "https://api.dexscreener.com/latest/dex/tokens/{}"


class PulsechainRotationAgent:
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=30.0)

        self.WATCH_TOKENS = {
            "PLS": "0xa1077a294dde1b09bb078844df40758a5d0f9a27",
            "PLSX": "0x95b303987a60c71504d99aa1b13b4da07b0790ab",
            "PROVEX": "0xf6f8db0aba00007681f8faf16a0fda1c9b030b11",
        }

        self.webhook = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
        self.history = defaultdict(lambda: deque(maxlen=20))
        self.last_alert_time = {}

    # ---------------- FETCH ----------------

    async def fetch_token_pairs(self, address):
        res = await self.client.get(DEX_URL.format(address))
        res.raise_for_status()
        data = res.json()
        return data.get("pairs", [])

    def choose_primary_pair(self, pairs):
        if not pairs:
            return None

        pulse_pairs = [p for p in pairs if p.get("chainId") == "pulsechain"]
        if not pulse_pairs:
            return None

        return max(
            pulse_pairs,
            key=lambda p: float((p.get("liquidity") or {}).get("usd") or 0),
        )

    # ---------------- DATA HELPERS ----------------

    def append_history(self, symbol, pair):
        self.history[symbol].append(pair)

    def get_pair(self, symbol):
        return self.history[symbol][-1] if self.history[symbol] else None

    def liquidity_usd(self, pair):
        return float((pair.get("liquidity") or {}).get("usd") or 0)

    def volume_24h(self, pair):
        return float((pair.get("volume") or {}).get("h24") or 0)

    def volume_liq(self, pair):
        liq = self.liquidity_usd(pair)
        vol = self.volume_24h(pair)
        return vol / liq if liq > 0 else 0.0

    def pressure(self, pair):
        txns = pair.get("txns") or {}
        h1 = txns.get("h1") or {}
        buys = float(h1.get("buys") or 0)
        sells = float(h1.get("sells") or 0)

        if sells == 0:
            return buys if buys > 0 else 1.0
        return buys / sells

    def price_change_1h(self, pair):
        return float((pair.get("priceChange") or {}).get("h1") or 0)

    def liquidity_growth_pct(self, symbol):
        hist = list(self.history[symbol])
        if len(hist) < 2:
            return 0.0

        first = float((hist[0].get("liquidity") or {}).get("usd") or 0)
        last = float((hist[-1].get("liquidity") or {}).get("usd") or 0)

        if first <= 0:
            return 0.0

        return ((last - first) / first) * 100

    def get_chart_link(self, pair):
        pair_address = pair.get("pairAddress")
        if pair_address:
            return f"https://dexscreener.com/pulsechain/{pair_address}"
        return "https://dexscreener.com"

    def format_money(self, v):
        v = float(v or 0)
        if v >= 1_000_000_000:
            return f"${v/1_000_000_000:.1f}B"
        if v >= 1_000_000:
            return f"${v/1_000_000:.1f}M"
        if v >= 1_000:
            return f"${v/1_000:.1f}K"
        return f"${v:.0f}"

    # ---------------- SIGNAL ENGINE ----------------

    def build_signal(self, symbol):
        pair = self.get_pair(symbol)
        if not pair:
            return None

        try:
            liquidity = self.liquidity_usd(pair)
            volume = self.volume_24h(pair)
            vol_liq = self.volume_liq(pair)
            pressure = self.pressure(pair)
            price_1h = self.price_change_1h(pair)
            liq_growth = self.liquidity_growth_pct(symbol)
            chart = self.get_chart_link(pair)
        except Exception as e:
            print(f"[{symbol}] data error: {e}", flush=True)
            return None

        if liquidity <= 0 or volume <= 0:
            return None

        # ⚠️ Anti-chase / extended move
        if price_1h >= 12 or vol_liq >= 3.5:
            return {
                "type": "EXTENDED",
                "symbol": symbol,
                "emoji": "⚠️",
                "title": "EXTENDED MOVE",
                "grade": "Late",
                "liquidity": liquidity,
                "volume": volume,
                "vol_liq": vol_liq,
                "pressure": pressure,
                "price_1h": price_1h,
                "liq_growth": liq_growth,
                "chart": chart,
                "note": "Move looks stretched — avoid chasing",
                "action": "🎯 Action: Wait for pullback / do not chase",
            }

        # 🚀 Confirmed sniper entry
        if (
            vol_liq >= 1.3
            and pressure >= 1.3
            and price_1h >= 0.5
            and liq_growth >= -1
        ):
            grade = "A+" if price_1h <= 6 and vol_liq <= 2.2 else "B"
            return {
                "type": "SNIPER",
                "symbol": symbol,
                "emoji": "🚀",
                "title": "SNIPER ENTRY",
                "grade": grade,
                "liquidity": liquidity,
                "volume": volume,
                "vol_liq": vol_liq,
                "pressure": pressure,
                "price_1h": price_1h,
                "liq_growth": liq_growth,
                "chart": chart,
                "note": "Breakout + volume expansion detected",
                "action": "🎯 Action: Momentum confirmed — consider entry",
            }

        # 👀 Earlier watchlist buildup
        if (
            vol_liq >= 0.9
            and pressure >= 1.15
            and price_1h >= -1.0
            and liq_growth >= -2
        ):
            return {
                "type": "WATCH",
                "symbol": symbol,
                "emoji": "👀",
                "title": "WATCHLIST BUILDUP",
                "grade": "Watch",
                "liquidity": liquidity,
                "volume": volume,
                "vol_liq": vol_liq,
                "pressure": pressure,
                "price_1h": price_1h,
                "liq_growth": liq_growth,
                "chart": chart,
                "note": "Flow is building, but breakout not fully confirmed yet",
                "action": "🎯 Action: Watch for confirmation / 1H strength",
            }

        return None

    # ---------------- ALERT CONTROL ----------------

    def should_send_signal(self, symbol):
        now = time.time()
        last = self.last_alert_time.get(symbol, 0)

        # 30 minute cooldown per token
        if now - last < 1800:
            return False

        return True

    def mark_signal_sent(self, symbol):
        self.last_alert_time[symbol] = time.time()

    # ---------------- TRADER TALK ----------------

    def trader_talk_ar(self, s):
        signal_type = s["type"]
        price_1h = s["price_1h"]
        pressure = s["pressure"]
        vol_liq = s["vol_liq"]
        liq_growth = s["liq_growth"]

        if signal_type == "SNIPER":
            if s["grade"] == "A+":
                return "🔥 فرصة قوية — دخول تدريجي، الزخم واضح والسيولة داعمة"
            if price_1h > 8:
                return "⚠️ الدخول ممكن لكن الحركة سريعة — لا تلاحق بكامل الكمية"
            if pressure >= 2:
                return "💥 شراء واضح من السوق — إذا بدك تدخل، خليه دخول ذكي مو دفعة وحدة"
            return "✅ الزخم تأكد — دخول تدريجي أفضل من المطاردة"

        if signal_type == "WATCH":
            if pressure >= 1.4 and price_1h < 0:
                return "👀 في تجميع محتمل — راقب الاختراق ولا تستعجل"
            if liq_growth > 2:
                return "💧 السيولة عم تدخل شوي شوي — فرصة قادمة إذا السعر أكد"
            return "📊 راقبها عن قرب — لسه بدها تأكيد"

        if signal_type == "EXTENDED":
            if price_1h >= 15:
                return "🚫 الحركة طايرة زيادة — خليك كاش ولا تلاحق"
            if vol_liq >= 4:
                return "⚠️ فومو عالي — انتبه للسيولة وخلّي عينك على التراجع"
            return "⚠️ متأخرة شوي — الأفضل تنتظر إعادة اختبار"

        return "📈 راقب السوق"

    # ---------------- FORMAT ----------------

    def format_signal(self, symbol, s):
        action_ar = self.trader_talk_ar(s)

        return (
            f"{s['emoji']} **{symbol} {s['title']}**\n\n"
            f"🏷️ Grade: {s['grade']}\n"
            f"💧 Liq: {self.format_money(s['liquidity'])} ({s['liq_growth']:+.1f}%)\n"
            f"📊 Vol/Liq: {s['vol_liq']:.2f}\n"
            f"💰 Vol: {self.format_money(s['volume'])}\n"
            f"⚖️ Pressure: {s['pressure']:.2f}\n"
            f"📈 1H: {s['price_1h']:+.2f}%\n\n"
            f"🧠 {s['note']}\n"
            f"{s['action']}\n"
            f"🇸🇦 {action_ar}\n"
            f"🔗 Chart: {s['chart']}"
        )

    # ---------------- DISCORD ----------------

    async def send_discord(self, message):
        if not self.webhook:
            print("DISCORD_WEBHOOK_URL missing", flush=True)
            return

        res = await self.client.post(self.webhook, json={"content": message})
        print("Discord status:", res.status_code, flush=True)
