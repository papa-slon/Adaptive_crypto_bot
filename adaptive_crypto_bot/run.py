# python -m adaptive_crypto_bot.run → точка входа Docker
from adaptive_crypto_bot.cli import cli
if __name__ == "__main__":
    cli()         # click auto-dispatch
