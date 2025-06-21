import asyncio, argparse
from adaptive_crypto_bot.core.exec_kernel import main as kernel_main

def parse_args():
    p = argparse.ArgumentParser(description="Adaptive Crypto Bot")
    p.add_argument("--once", action="store_true", help="запустить и выйти после 1 цикла")
    return p.parse_args()

def main():
    args = parse_args()
    if args.once:
        asyncio.run(kernel_main())
    else:
        # future: watchdog / autoreloader
        asyncio.run(kernel_main())

if __name__ == "__main__":
    main()
