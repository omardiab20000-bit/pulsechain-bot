import asyncio
from pulsechain_rotation_agent import PulsechainRotationAgent

async def main():
    agent = PulsechainRotationAgent()

    print("BOT STARTING", flush=True)
    await agent.send_discord("✅ Bot LIVE - scanning PulseChain...")

    while True:
        try:
            # 🔍 Scan tokens and update data
            for symbol, address in agent.WATCH_TOKENS.items():
                try:
                    pairs = await agent.fetch_token_pairs(address)
                    primary = agent.choose_primary_pair(pairs)

                    if primary:
                        agent.append_history(symbol, primary)

                except Exception as e:
                    print(f"[{symbol}] scan error: {e}", flush=True)

            # 🎯 Check for sniper signals
            for symbol in agent.WATCH_TOKENS.keys():
                try:
                    signal = agent.build_signal(symbol)

                    if signal and agent.should_send_signal(symbol):
                        await agent.send_discord(
                            agent.format_signal(symbol, signal)
                        )
                        agent.mark_signal_sent(symbol)

                except Exception as e:
                    print(f"[{symbol}] signal error: {e}", flush=True)

            # ⏱️ Wait before next scan (5 minutes)
            await asyncio.sleep(300)

        except Exception as e:
            print("LOOP ERROR:", e, flush=True)
            await asyncio.sleep(60)

# 🚀 Run bot
asyncio.run(main())
