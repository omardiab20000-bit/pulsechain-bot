import asyncio
from pulsechain_rotation_agent import PulsechainRotationAgent

async def main():
    agent = PulsechainRotationAgent()

    print("BOT STARTING", flush=True)
    await agent.send_discord("✅ Bot LIVE - scanning PulseChain...")

    while True:
        try:
            for symbol, address in agent.WATCH_TOKENS.items():
                try:
                    pairs = await agent.fetch_token_pairs(address)
                    primary = agent.choose_primary_pair(pairs)

                    if primary:
                        agent.append_history(symbol, primary)

                except Exception as e:
                    print(f"[{symbol}] error: {e}", flush=True)

            for symbol in agent.WATCH_TOKENS.keys():
                signal = agent.build_signal(symbol)

                if signal and agent.should_send_signal(symbol, signal):
                    await agent.send_discord(agent.format_signal(symbol, signal))
                    agent.mark_signal_sent(symbol, signal)

            await asyncio.sleep(300)

        except Exception as e:
            print("LOOP ERROR:", e, flush=True)
            await asyncio.sleep(60)

asyncio.run(main())
