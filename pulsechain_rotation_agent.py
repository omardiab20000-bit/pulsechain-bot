import os
import httpx


DEX_URL = "https://api.dexscreener.com/latest/dex/tokens/{}"


class PulsechainRotationAgent:
    WATCH_TOKENS = {
        "PLS": "0xa1077a294dde1b09bb078844df40758a5d0f9a27",
        "PLSX": "0x95b303987a60c71504d99aa1b13b4da07b0790ab",
        "PROVEX": "0xf6f8db0aba00007681f8faf16a0fda1c9b030b11",
    }

    def __init__(self):
        self.client = httpx.AsyncClient(timeout=30.0)
        self.history = {}
        self.webhook = os.getenv("DISCORD_WEBHOOK_URL", "").strip()

    async def fetch_token_pairs(self, address):
        r = await self.client.get(DEX_URL.format(address))
        r.raise_for_status()
        data = r.json()
        return data.get("pairs", [])

    def choose_primary_pair(self, pairs):
        if not pairs:
            return None

        pulse_pairs = [p for p in pairs if p.get("chainId") == "pulsechain"]
        if not pulse_pairs:
            return None

        return max(
            pulse_pairs,
            key=lambda x: float((x.get("liquidity") or {}).get("usd") or 0),
        )

    def append_history(self, symbol, pair):
        self.history[symbol] = pair

    def volume_liq(self, pair):
        liq = float((pair.get("liquidity") or {}).get("usd") or 0)
        vol = float((pair.get("volume") or {}).get("h24") or 0)
        if liq <= 0:
            return 0.0
        return vol / liq

    def pressure(self, pair):
        txns = pair.get("txns") or {}
        h1 = txns.get("h1") or {}
        buys = int(h1.get("buys") or 0)
        sells = int(h1.get("sells") or 0)

        if sells == 0:
            return float(buys) if buys > 0 else 1.0
        return buys / sells

    def should_alert(self, symbol):
        pair = self.history.get(symbol)
        if not pair:
            return False

        vliq = self.volume_liq(pair)
        return vliq > 1.0

    def format_money(self, x):
        x = float(x or 0)
        if x >= 1_000_000_000:
            return f"${x/1_000_000_000:.1f}B"
        if x >= 1_000_000:
            return f"${x/1_000_000:.1f}M"
        if x >= 1_000:
            return f"${x/1_000:.1f}K"
        return f"${x:.0f}"

    def format_signal(self, symbol):
        p = self.history[symbol]

        liq = float((p.get("liquidity") or {}).get("usd") or 0)
        vol = float((p.get("volume") or {}).get("h24") or 0)
        vliq = self.volume_liq(p)
        pres = self.pressure(p)
        price_change = float((p.get("priceChange") or {}).get("h1") or 0)

        if
