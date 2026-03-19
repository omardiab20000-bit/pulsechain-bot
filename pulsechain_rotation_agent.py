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

        self.FAST_SCAN_SECONDS = int(os.getenv("FAST_SCAN_SECONDS", "300"))
        self.SUMMARY_SECONDS = int(os.getenv("SUMMARY_SECONDS", "14400"))
        self.ALERT_COOLDOWN_SECONDS = int(os.getenv("ALERT_COOLDOWN_SECONDS", "1800"))

        self.STABLE_SYMBOLS = {"USDC", "USDT", "DAI"}

        self.history = defaultdict(lambda: deque(maxlen=24))
        self.last_alert_time = {}
        self.last_summary_time = 0.0

    # ---------------- FETCH ----------------

    async def fetch_token_pairs(self, address):
        res = await self.client.get(DEX_URL.format(address))
        res.raise_for_status()
        data = res.json()
        return data.get("pairs", [])

    def choose_primary_pair(self, pairs):
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

    def quote_symbol(self, pair):
        quote = pair.get("quoteToken") or {}
        return str(quote.get("symbol") or "").upper()

    def is_stable_quoted(self, pair):
        return self.quote_symbol(pair) in self.STABLE_SYMBOLS

    # ---------------- FORMAT ----------------

    def format_money(self, v):
        v = float(v or 0)
        if v >= 1_000_000_000:
            return f"${v/1_000_000_000:.2f}B"
        if v >= 1_000_000:
            return f"${v/1_000_000:.2f}M"
        if v >= 1_000:
            return f"${v/1_000:.2f}K"
        return f"${v:.2f}"

    # ---------------- FLOW ENGINE ----------------

    def flow_read(self, symbol):
        pair = self.get_pair(symbol)
        if not pair:
            return "Flow unclear"

        pressure = self.pressure(pair)
        price_1h = self.price_change_1h(pair)
        vol_liq = self.volume_liq(pair)
        liq_growth = self.liquidity_growth_pct(symbol)

        pls = self.get_pair("PLS")
        plsx = self.get_pair("PLSX")

        pls_score = None
        plsx_score = None

        if pls:
            pls_score = (
                self.volume_liq(pls) * 30
                + max(self.pressure(pls) - 1, 0) * 25
                + max(self.price_change_1h(pls), 0) * 3
                + max(self.liquidity_growth_pct("PLS"), 0) * 2
            )

        if plsx:
            plsx_score = (
                self.volume_liq(plsx) * 30
                + max(self.pressure(plsx) - 1, 0) * 25
                + max(self.price_change_1h(plsx), 0) * 3
                + max(self.liquidity_growth_pct("PLSX"), 0) * 2
            )

        if symbol == "PLS" and pls_score is not None and plsx_score is not None:
            if pls_score > plsx_score * 1.15:
                return "Flow favors PLS over PLSX"
            if plsx_score > pls_score * 1.15:
                return "Flow still stronger in PLSX"

        if symbol == "PLSX" and pls_score is not None and plsx_score is not None:
            if plsx_score > pls_score * 1.15:
                return "Flow favors PLSX over PLS"
            if pls_score > plsx_score * 1.15:
                return "Flow still stronger in PLS"

        if self.is_stable_quoted(pair):
            if pressure < 1 and price_1h < 0:
                return "Defensive flow / stable pair pressure increasing"
            if pressure > 1.2 and vol_liq > 1:
                return f"Risk-on flow building into {symbol}"

        if pressure >= 1.4 and vol_liq >= 1 and price_1h >= 0:
            return f"Strong inflow into {symbol}"

        if pressure >= 1.15 and price_1h > -1:
            return f"Flow building into {symbol}"

        if pressure < 1 and price_1h < 0:
            return "Defensive tone / sellers active"

        return "Flow mixed / not decisive yet"

    # ---------------- ARABIC TRADER TALK ----------------

    def trader_talk_ar(self, signal):
        t = signal["type"]
        p = signal["pressure"]
        h = signal["price_1h"]
        lg = signal["liq_growth"]

        if t == "SNIPER":
            if signal["grade"] == "A+":
                return "🔥 فرصة قوية — دخول تدريجي، الزخم واضح والسيولة داعمة"
            if p >= 2:
                return "💥 شراء واضح من السوق — ادخل بهدوء ولا تفوت بكامل الكمية"
            return "✅ الاختراق تأكد — إذا بدك تدخل خليه دخول ذكي"

        if t == "WATCH":
            if p >= 1.8 and h < 0:
                return "👀 في تجميع محتمل — راقب الاختراق ولا تستعجل"
            if lg > 2:
                return "💧 السيولة عم تدخل — فرصة قادمة إذا السعر أكد"
            return "📊 راقبها عن قرب — لسه بدها تأكيد"

        if t == "EXTENDED":
            return "⚠️ انتبه — خليك كاش لا تلاحق"

        if t == "BRAIN":
            return signal.get("action_ar", "🧠 في حركة مهمّة بالسوق")

        return "📈 راقب السوق"

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
            flow = self.flow_read(symbol)
        except Exception as e:
            print(f"[{symbol}] data error: {e}", flush=True)
            return None

        if liquidity <= 0 or volume <= 0:
            return None

        # Brain mode: core assets
        if symbol in ("PLS", "PLSX") and liq_growth >= 4 and pressure >= 1.1 and vol_liq >= 0.7:
            return {
                "type": "BRAIN",
                "symbol": symbol,
                "color": 0x3498DB,
                "title": "🧠 LIQUIDITY BUILDUP",
                "grade": "Brain",
                "note": "Liquidity is building on a core asset",
                "flow": flow,
                "action": "🎯 Action: Track closely / market may be preparing a bigger move",
                "action_ar": "🧠 انتبه — السيولة عم تتجمع، ممكن حركة أكبر قادمة",
                "chart": chart,
                "liquidity": liquidity,
                "volume": volume,
                "vol_liq": vol_liq,
                "pressure": pressure,
                "price_1h": price_1h,
                "liq_growth": liq_growth,
            }

        # Extended
        if price_1h >= 12 or vol_liq >= 3.5:
            return {
                "type": "EXTENDED",
                "symbol": symbol,
                "color": 0xE74C3C,
                "title": "⚠️ EXTENDED MOVE",
                "grade": "Late",
                "note": "Move looks stretched — avoid chasing",
                "flow": flow,
                "action": "🎯 Action: Wait for pullback / do not chase",
                "chart": chart,
                "liquidity": liquidity,
                "volume": volume,
                "vol_liq": vol_liq,
                "pressure": pressure,
                "price_1h": price_1h,
                "liq_growth": liq_growth,
            }

        # Sniper
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
                "color": 0x2ECC71,
                "title": "🚀 SNIPER ENTRY",
                "grade": grade,
                "note": "Breakout + volume expansion detected",
                "flow": flow,
                "action": "🎯 Action: Momentum confirmed — consider entry",
                "chart": chart,
                "liquidity": liquidity,
                "volume": volume,
                "vol_liq": vol_liq,
                "pressure": pressure,
                "price_1h": price_1h,
                "liq_growth": liq_growth,
            }

        # Watch
        if (
            vol_liq >= 0.9
            and pressure >= 1.15
            and price_1h >= -1.0
            and liq_growth >= -2
        ):
            return {
                "type": "WATCH",
                "symbol": symbol,
                "color": 0xF1C40F,
                "title": "👀 WATCHLIST BUILDUP",
                "grade": "Watch",
                "note": "Flow is building, but breakout not fully confirmed yet",
                "flow": flow,
                "action": "🎯 Action: Watch for confirmation / 1H strength",
                "chart": chart,
                "liquidity": liquidity,
                "volume": volume,
                "vol_liq": vol_liq,
                "pressure": pressure,
                "price_1h": price_1h,
                "liq_growth": liq_growth,
            }

        return None

    # ---------------- SUMMARY / LEADERBOARD ----------------

    def summary_due(self):
        return time.time() - self.last_summary_time >= self.SUMMARY_SECONDS

    def mark_summary_sent(self):
        self.last_summary_time = time.time()

    def build_leaderboard_summary(self):
        rows = []

        for symbol in self.WATCH_TOKENS.keys():
            pair = self.get_pair(symbol)
            if not pair:
                continue

            liq = self.liquidity_usd(pair)
            vol = self.volume_24h(pair)
            vol_liq = self.volume_liq(pair)
            pressure = self.pressure(pair)
            price_1h = self.price_change_1h(pair)
            liq_growth = self.liquidity_growth_pct(symbol)
            score = (vol_liq * 30) + (max(pressure - 1, 0) * 20) + (max(price_1h, 0) * 3) + (max(liq_growth, 0) * 2)

            rows.append({
                "symbol": symbol,
                "score": score,
                "liq": liq,
                "vol": vol,
                "vol_liq": vol_liq,
                "pressure": pressure,
                "price_1h": price_1h,
                "liq_growth": liq_growth,
                "flow": self.flow_read(symbol),
            })

        if not rows:
            return None

        rows.sort(key=lambda x: x["score"], reverse=True)
        top = rows[:3]

        embed = {
            "title": "🏆 4H Leaderboard / Market Pulse",
            "color": 0x9B59B6,
            "description": "Top rotation / liquidity activity across PLS, PLSX, PROVEX",
            "fields": [],
        }

        for i, row in enumerate(top, start=1):
            value = (
                f"💧 Liq: {self.format_money(row['liq'])} ({row['liq_growth']:+.1f}%)\n"
                f"📊 Vol/Liq: {row['vol_liq']:.2f}\n"
                f"⚖️ Pressure: {row['pressure']:.2f}\n"
                f"📈 1H: {row['price_1h']:+.2f}%\n"
                f"➡️ {row['flow']}"
            )
            embed["fields"].append({
                "name": f"{i}️⃣ {row['symbol']}",
                "value": value,
                "inline": False
            })

        embed["fields"].append({
            "name": "🇸🇦 قراءة السوق",
            "value": "إذا PLS أو PLSX عم يجمعوا سيولة، راقب السوق لأنه ممكن يكون في حركة أكبر. وإذا صار الميل دفاعي، خليك واعي على السيولة والـ stables.",
            "inline": False
        })

        return {"embeds": [embed]}

    # ---------------- ALERT CONTROL ----------------

    def should_send_signal(self, symbol):
        now = time.time()
        last = self.last_alert_time.get(symbol, 0)
        return now - last > self.ALERT_COOLDOWN_SECONDS

    def mark_signal_sent(self, symbol):
        self.last_alert_time[symbol] = time.time()

    # ---------------- EMBED ----------------

    def build_embed_payload(self, signal):
        action_ar = self.trader_talk_ar(signal)

        embed = {
            "title": f"{signal['symbol']} {signal['title']}",
            "color": signal["color"],
            "fields": [
                {"name": "🏷️ Grade", "value": signal["grade"], "inline": True},
                {"name": "💧 Liquidity", "value": self.format_money(signal["liquidity"]), "inline": True},
                {"name": "📊 Vol/Liq", "value": f"{signal['vol_liq']:.2f}", "inline": True},
                {"name": "💰 Volume", "value": self.format_money(signal["volume"]), "inline": True},
                {"name": "⚖️ Pressure", "value": f"{signal['pressure']:.2f}", "inline": True},
                {"name": "📈 1H", "value": f"{signal['price_1h']:+.2f}%", "inline": True},
                {"name": "💧 Liquidity Δ", "value": f"{signal['liq_growth']:+.1f}%", "inline": True},
                {"name": "➡️ Flow", "value": signal["flow"], "inline": False},
                {"name": "🧠 Insight", "value": signal["note"], "inline": False},
                {"name": "🎯 Action", "value": signal["action"], "inline": False},
                {"name": "🇸🇦 قرار السوق", "value": action_ar, "inline": False},
                {"name": "🔗 Chart", "value": signal["chart"], "inline": False},
            ],
        }

        return {"embeds": [embed]}

    async def send_discord_text(self, text):
        if not self.webhook:
            print("DISCORD_WEBHOOK_URL missing", flush=True)
            return

        res = await self.client.post(self.webhook, json={"content": text})
        print("Discord status:", res.status_code, flush=True)

    async def send_discord(self, signal_or_payload):
        if not self.webhook:
            print("DISCORD_WEBHOOK_URL missing", flush=True)
            return

        if isinstance(signal_or_payload, dict) and "embeds" in signal_or_payload:
            payload = signal_or_payload
        elif isinstance(signal_or_payload, dict):
            payload = self.build_embed_payload(signal_or_payload)
        else:
            payload = {"content": str(signal_or_payload)}

        res = await self.client.post(self.webhook, json=payload)
        print("Discord status:", res.status_code, flush=True)
