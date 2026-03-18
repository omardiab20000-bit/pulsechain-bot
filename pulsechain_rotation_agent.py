import httpx, os

DEX = "https://api.dexscreener.com/latest/dex/tokens/{}"

class PulsechainRotationAgent:

    WATCH_TOKENS = {
        "PLS": "0xa1077a294dde1b09bb078844df40758a5d0f9a27",
        "PLSX": "0x95b303987a60c71504d99aa1b13b4da07b0790ab",
        "PROVEX": "0xf6f8db0aba00007681f8faf16a0fda1c9b030b11",
    }

    def __init__(self):
        self.client = httpx.AsyncClient()
        self.history = {}
        self.last_alert_at = {}
        self.webhook = os.getenv("DISCORD_WEBHOOK_URL")

    async def fetch_token_pairs(self, address):
        r = await self.client.get(DEX.format(address))
        return r.json().get("pairs", [])

    def choose_primary_pair(self, pairs):
        if not pairs:
            return None
        return max(pairs, key=lambda x: x.get("liquidity", {}).get("usd", 0))

    def append_history(self, symbol, pair):
        self.history[symbol] = pair

    def volume_liq(self, pair):
        liq = pair.get("liquidity", {}).get("usd", 1)
        vol = pair.get("volume", {}).get("h24", 0)
        return vol / liq if liq else 0

    def pressure(self, pair):
        buys = pair.get("txns", {}).get("h1", {}).get("buys", 1)
        sells = pair.get("txns", {}).get("h1", {}).get("sells", 1)
        return buys / sells if sells else buys

    def should_alert(self, symbol):
        if symbol not in self.history:
            return False
        return self.volume_liq(self.history[symbol]) > 1

    def format_money(self, x):
        if x > 1_000_000:
            return f"${x/1_000_000:.1f}M"
        if x > 1_000:
            return f"${x/1_000:.1f}K"
        return f"${x}"

    def format_signal(self, symbol):
        p = self.history[symbol]

        liq = p.get("liquidity", {}).get("usd", 0)
        vol = p.get("volume", {}).get("h24", 0)
        vliq = self.volume_liq(p)
        pres = self.pressure(p)

        if vliq > 1.5:
            emoji = "🔥"
            action = "Consider entry"
        else:
            emoji = "🟡"
            action = "Watch"

        return (
            f"{emoji} {symbol} Signal\n"
            f"💧 Liq: ${liq:,.0f}\n"
            f"📊 Vol/Liq: {vliq:.2f}\n"
            f"💰 Vol: {self.format_money(vol)}\n"
            f"⚖️ Pressure: {pres:.2f}\n"
            f"🎯 Action: {action}"
        )

    async def send_discord(self, msg):
        if not self.webhook:
            return
        await self.client.post(self.webhook, json={"content": msg})