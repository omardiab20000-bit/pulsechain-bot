import asyncio
from pulsechain_rotation_agent import PulsechainRotationAgent


async def main():
    agent = PulsechainRotationAgent()

    print("BOT STARTING", flush=True)
    await agent.send_discord_text("✅ Bot LIVE - scanning PulseChain...")

    while True:
        try:
            # scan all watched tokens
            for symbol, address in agent.WATCH_TOKENS.items():
                try:
                    pairs = await agent.fetch_token_pairs(address)
                    primary = agent.choose_primary_pair(pairs)
                    if primary:
                        agent.append_history(symbol, primary)
                except Exception as e:
                    print(f"[{symbol}] scan error: {e}", flush=True)

            # send token signals
            for symbol in agent.WATCH_TOKENS.keys():
                try:
                    signal = agent.build_signal(symbol)
                    if signal and agent.should_send_signal(symbol):
                        await agent.send_discord(signal)
                        agent.mark_signal_sent(symbol)
                except Exception as e:
                    print(f"[{symbol}] signal error: {e}", flush=True)

            # periodic summary / leaderboard
            try:
                if agent.summary_due():
                    summary = agent.build_leaderboard_summary()
                    if summary:
                        await agent.send_discord(summary)
                    agent.mark_summary_sent()
            except Exception as e:
                print(f"[SUMMARY] error: {e}", flush=True)

            await asyncio.sleep(agent.FAST_SCAN_SECONDS)

        except Exception as e:
            print(f"LOOP ERROR: {e}", flush=True)
            await asyncio.sleep(60)


if __name__ == "__main__":
    asyncio.run(main())
