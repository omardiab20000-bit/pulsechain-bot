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

        self.SYMBOL_AR = {
            "PLS": "عملة بولس",
            "PLSX": "عملة بولس إكس",
            "PROVEX": "عملة بروفكس",
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

    # ---------------- FORMAT / VISUALS ----------------

    def format_money(self, v):
        v = float(v or 0)
        if v >= 1_000_000_000:
            return f"${v/1_000_000_000:.2f}B"
        if v >= 1_000_000:
            return f"${v/1_000_000:.2f}M"
        if v >= 1_000:
            return f"${v/1_000:.2f}K"
        return f"${v:.2f}"

    def rank_badge(self, rank):
        badges = {1: "🥇", 2: "🥈", 3: "🥉"}
        return badges.get(rank, "📍")

    def symbol_emoji(self, symbol):
        mapping = {
            "PLS": "🔴",
            "PLSX": "🟣",
            "PROVEX": "🔵",
        }
        return mapping.get(symbol, "🪙")

    def pressure_emoji(self, pressure):
        if pressure >= 2:
            return "🔥"
        if pressure >= 1.2:
            return "🟢"
        if pressure >= 0.9:
            return "🟡"
        return "🔻"

    def volliq_emoji(self, vol_liq):
        if vol_liq >= 1.5:
            return "🚀"
        if vol_liq >= 0.8:
            return "📈"
        if vol_liq >= 0.3:
            return "📊"
        return "🧊"

    def liq_emoji(self, liq_growth):
        if liq_growth >= 5:
            return "🌊"
        if liq_growth >= 1:
            return "💧"
        if liq_growth > -1:
            return "🪙"
        return "🥀"

    def flow_score_emoji(self, score):
        if score >= 8:
            return "🔥"
        if score >= 6:
            return "🟢"
        if score >= 4:
            return "🟡"
        return "🔻"

    def flow_score_label_ar(self, score):
        if score >= 8:
            return "قوي جداً"
        if score >= 6:
            return "قوي"
        if score >= 4:
            return "متوسط"
        return "ضعيف"

    def symbol_name_ar(self, symbol):
        return self.SYMBOL_AR.get(symbol, f"عملة {symbol}")

    def signal_title_clean(self, signal):
        return f"{signal['symbol']} Coin"

    def one_liner_market_read_ar(self, row):
        symbol = row["symbol"]
        pressure = row["pressure"]
        vol_liq = row["vol_liq"]
        price_1h = row["price_1h"]
        liq_growth = row["liq_growth"]

        if pressure >= 2 and vol_liq >= 1:
            return f"شراء واضح على {symbol} والزخم صاحي."
        if pressure >= 1.2 and liq_growth > 0:
            return f"في تجميع محترم على {symbol} والسيولة تتحسن."
        if pressure < 1 and price_1h < 0:
            return f"{symbol} عليه ضغط بيع والسوق حذر."
        if vol_liq < 0.25:
            return f"الحركة على {symbol} هادئة والسيولة بطيئة."
        return f"{symbol} تحت المراقبة، لسه الإشارة مو محسومة."

    # ---------------- FLOW ENGINE ----------------

    def flow_score(self, symbol):
        pair = self.get_pair(symbol)
        if not pair:
            return 0

        pressure = self.pressure(pair)
        price_1h = self.price_change_1h(pair)
        vol_liq = self.volume_liq(pair)
        liq_growth = self.liquidity_growth_pct(symbol)

        score = 0.0

        if pressure >= 2.0:
            score += 3.0
        elif pressure >= 1.5:
            score += 2.4
        elif pressure >= 1.2:
            score += 1.8
        elif pressure >= 1.0:
            score += 1.0
        else:
            score += 0.2

        if vol_liq >= 1.5:
            score += 3.0
        elif vol_liq >= 1.0:
            score += 2.4
        elif vol_liq >= 0.7:
            score += 1.8
        elif vol_liq >= 0.3:
            score += 1.0
        else:
            score += 0.2

        if price_1h >= 6:
            score += 2.0
        elif price_1h >= 2:
            score += 1.5
        elif price_1h >= 0:
            score += 1.0
        elif price_1h > -2:
            score += 0.5
        else:
            score += 0.1

        if liq_growth >= 5:
            score += 2.0
        elif liq_growth >= 2:
            score += 1.5
        elif liq_growth >= 0:
            score += 1.0
        elif liq_growth > -2:
            score += 0.5
        else:
            score += 0.1

        return max(0, min(10, round(score)))

    def flow_read(self, symbol):
        pair = self.get_pair(symbol)
        if not pair:
            return "Flow unclear"

        pressure = self.pressure(pair)
        price_1h = self.price_change_1h(pair)
        vol_liq = self.volume_liq(pair)

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

    def flow_read_ar(self, symbol):
        flow = self.flow_read(symbol)

        mapping = {
            "Flow favors PLS over PLSX": "السيولة تميل بوضوح نحو PLS أكثر من PLSX",
            "Flow still stronger in PLSX": "السيولة ما تزال أقوى في PLSX",
            "Flow favors PLSX over PLS": "السيولة تميل بوضوح نحو PLSX أكثر من PLS",
            "Flow still stronger in PLS": "السيولة ما تزال أقوى في PLS",
            "Defensive flow / stable pair pressure increasing": "تدفق دفاعي — الضغط يتجه نحو أزواج الستيبِل",
            "Risk-on flow building into PLS": "شهية المخاطرة ترتفع والسيولة تبدأ تدخل إلى PLS",
            "Risk-on flow building into PLSX": "شهية المخاطرة ترتفع والسيولة تبدأ تدخل إلى PLSX",
            "Risk-on flow building into PROVEX": "شهية المخاطرة ترتفع والسيولة تبدأ تدخل إلى PROVEX",
            "Strong inflow into PLS": "في دخول قوي وواضح على PLS",
            "Strong inflow into PLSX": "في دخول قوي وواضح على PLSX",
            "Strong inflow into PROVEX": "في دخول قوي وواضح على PROVEX",
            "Flow building into PLS": "السيولة تتجمع تدريجياً على PLS",
            "Flow building into PLSX": "السيولة تتجمع تدريجياً على PLSX",
            "Flow building into PROVEX": "السيولة تتجمع تدريجياً على PROVEX",
            "Defensive tone / sellers active": "السوق دفاعي حالياً والبائعين نشطين",
            "Flow mixed / not decisive yet": "التدفق مختلط ولسه الاتجاه غير محسوم",
            "Flow unclear": "التدفق غير واضح حالياً",
        }

        return mapping.get(flow, "قراءة التدفق غير واضحة حالياً")

    # ---------------- ARABIC TRADER TALK ----------------

    def trader_talk_ar(self, signal):
        t = signal["type"]
        p = signal["pressure"]
        h = signal["price_1h"]
        lg = signal["liq_growth"]
        fscore = signal.get("flow_score", 0)

        if t == "SNIPER":
            if signal["grade"] == "A+":
                return f"🔥 فرصة قوية — التدفق {fscore}/10 والزخم واضح والسيولة داعمة"
            if p >= 2:
                return f"💥 شراء واضح من السوق — التدفق {fscore}/10، ادخل بهدوء"
            return f"✅ الاختراق تأكد — التدفق {fscore}/10"

        if t == "WATCH":
            if p >= 1.8 and h < 0:
                return f"👀 في تجميع محتمل — التدفق {fscore}/10، راقب التأكيد"
            if lg > 2:
                return f"💧 السيولة عم تدخل — التدفق {fscore}/10، فرصة قادمة إذا السعر أكد"
            return f"📊 راقبها عن قرب — التدفق {fscore}/10 ولسه بدها تأكيد"

        if t == "EXTENDED":
            return f"⚠️ انتبه — الحركة ممدودة حتى لو التدفق {fscore}/10، لا تلاحق"

        if t == "BRAIN":
            return signal.get("action_ar", f"🧠 في حركة مهمّة بالسوق — التدفق {fscore}/10")

        return f"📈 راقب السوق — التدفق {fscore}/10"

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
            flow_score = self.flow_score(symbol)
        except Exception as e:
            print(f"[{symbol}] data error: {e}", flush=True)
            return None

        if liquidity <= 0 or volume <= 0:
            return None

        if symbol in ("PLS", "PLSX") and liq_growth >= 4 and pressure >= 1.1 and vol_liq >= 0.7:
            return {
                "type": "BRAIN",
                "symbol": symbol,
                "color": 0x3498DB,
                "title": "🧠 LIQUIDITY BUILDUP",
                "grade": "Brain",
                "note": "Liquidity is building on a core asset",
                "note_ar": "السيولة عم تتجمع على أصل أساسي وقد تسبق حركة أكبر",
                "flow": flow,
                "flow_score": flow_score,
                "action": "🎯 Track closely / market may be preparing a bigger move",
                "action_ar": f"🧠 انتبه — السيولة عم تتجمع، التدفق {flow_score}/10، ممكن حركة أكبر قادمة",
                "chart": chart,
                "liquidity": liquidity,
                "volume": volume,
                "vol_liq": vol_liq,
                "pressure": pressure,
                "price_1h": price_1h,
                "liq_growth": liq_growth,
            }

        if price_1h >= 12 or vol_liq >= 3.5:
            return {
                "type": "EXTENDED",
                "symbol": symbol,
                "color": 0xE74C3C,
                "title": "⚠️ EXTENDED MOVE",
                "grade": "Late",
                "note": "Move looks stretched — avoid chasing",
                "note_ar": "الحركة ممدودة أكثر من اللازم — الأفضل عدم الملاحقة",
                "flow": flow,
                "flow_score": flow_score,
                "action": "🎯 Wait for pullback / do not chase",
                "action_ar": f"⚠️ خفف اندفاعك — التدفق {flow_score}/10 لكن الحركة ممدودة",
                "chart": chart,
                "liquidity": liquidity,
                "volume": volume,
                "vol_liq": vol_liq,
                "pressure": pressure,
                "price_1h": price_1h,
                "liq_growth": liq_growth,
            }

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
                "note_ar": "اختراق مع توسع بالحجم — الزخم حاضر",
                "flow": flow,
                "flow_score": flow_score,
                "action": "🎯 Momentum confirmed — consider entry",
                "action_ar": f"🚀 الزخم متأكد — التدفق {flow_score}/10، ادخل بحذر وذكاء",
                "chart": chart,
                "liquidity": liquidity,
                "volume": volume,
                "vol_liq": vol_liq,
                "pressure": pressure,
                "price_1h": price_1h,
                "liq_growth": liq_growth,
            }

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
                "title": "👀 WATCH",
                "grade": "Watch",
                "note": "Flow is building, but breakout not fully confirmed yet",
                "note_ar": "التدفق يتحسن، لكن الاختراق لم يتأكد بالكامل بعد",
                "flow": flow,
                "flow_score": flow_score,
                "action": "🎯 Watch for confirmation / 1H strength",
                "action_ar": f"👀 راقب التأكيد وقوة الساعة — التدفق {flow_score}/10",
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
            flow_score = self.flow_score(symbol)

            score = (
                (vol_liq * 30)
                + (max(pressure - 1, 0) * 20)
                + (max(price_1h, 0) * 3)
                + (max(liq_growth, 0) * 2)
            )

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
                "flow_ar": self.flow_read_ar(symbol),
                "flow_score": flow_score,
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

        separator = "━━━━━━━━━━━━━━━━━━━━━━"

        for i, row in enumerate(top, start=1):
            rank = self.rank_badge(i)
            symbol_icon = self.symbol_emoji(row["symbol"])
            pressure_icon = self.pressure_emoji(row["pressure"])
            vol_icon = self.volliq_emoji(row["vol_liq"])
            liq_icon = self.liq_emoji(row["liq_growth"])
            quick_read_ar = self.one_liner_market_read_ar(row)
            flow_score = row["flow_score"]
            flow_score_icon = self.flow_score_emoji(flow_score)
            flow_score_label = self.flow_score_label_ar(flow_score)

            value = (
                f"{liq_icon} **Liquidity / السيولة**: {self.format_money(row['liq'])} ({row['liq_growth']:+.1f}%)\n"
                f"{vol_icon} **Vol/Liq / الحجم إلى السيولة**: {row['vol_liq']:.2f}\n"
                f"{pressure_icon} **Pressure / القوة**: {row['pressure']:.2f}\n"
                f"⏱️ **1H Move / حركة الساعة**: {row['price_1h']:+.2f}%\n"
                f"{flow_score_icon} **Flow Score / تقييم التدفق**: {flow_score}/10 ({flow_score_label})\n"
                f"🧭 **Flow / تدفق السيولة**: {row['flow']}\n"
                f"🇸🇦 **التدفق**: {row['flow_ar']}\n"
                f"📌 **الخلاصة**: {quick_read_ar}\n"
                f"{separator}"
            )

            embed["fields"].append({
                "name": f"{rank} {symbol_icon} {row['symbol']} — {self.symbol_name_ar(row['symbol'])}",
                "value": value,
                "inline": False
            })

        embed["fields"].append({
            "name": "🧠 قراءة السوق",
            "value": (
                "إذا شفت تقييم التدفق عالي مع ضغط شراء وسيولة تتحسن، غالباً في حركة عم تنبني فعلياً. "
                "أما إذا كان التقييم ضعيف أو متوسط، خليك مراقب أكثر من كونك مندفع."
            ),
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
        fscore = signal.get("flow_score", 0)
        fscore_icon = self.flow_score_emoji(fscore)
        fscore_label = self.flow_score_label_ar(fscore)
        symbol_ar = self.symbol_name_ar(signal["symbol"])

        embed = {
            "title": self.signal_title_clean(signal),
            "description": f"{symbol_ar}",
            "color": signal["color"],
            "fields": [
                {"name": "🪙 Coin / العملة", "value": f"{signal['symbol']} — {symbol_ar}", "inline": False},
                {"name": "🏷️ Grade / التصنيف", "value": signal["grade"], "inline": True},
                {"name": "💧 Liquidity / السيولة", "value": self.format_money(signal["liquidity"]), "inline": True},
                {"name": "📊 Vol/Liq / الحجم إلى السيولة", "value": f"{signal['vol_liq']:.2f}", "inline": True},
                {"name": "💰 Volume / الحجم", "value": self.format_money(signal["volume"]), "inline": True},
                {"name": "⚖️ Pressure / القوة", "value": f"{signal['pressure']:.2f}", "inline": True},
                {"name": "📈 1H / حركة الساعة", "value": f"{signal['price_1h']:+.2f}%", "inline": True},
                {"name": "💧 Liquidity Δ / تغير السيولة", "value": f"{signal['liq_growth']:+.1f}%", "inline": True},
                {"name": f"{fscore_icon} Flow Score / تقييم التدفق", "value": f"{fscore}/10 ({fscore_label})", "inline": True},
                {"name": "🧭 Flow / تدفق السيولة", "value": f"{signal['flow']}\n{self.flow_read_ar(signal['symbol'])}", "inline": False},
                {"name": "🧠 Insight / نظرة", "value": f"{signal['note']}\n{signal.get('note_ar', '')}\n\u200b\n\u200b", "inline": False},
                {"name": "🎯 Action / الإجراء", "value": f"{signal['action']}\n{action_ar}", "inline": False},
                {"name": "🔗 Chart / الشارت", "value": signal["chart"], "inline": False},
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
