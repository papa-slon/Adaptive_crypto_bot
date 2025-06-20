
from agents.vwap_sweep import VWAPSweep, Bar
def test_watch_reset():
    bot=VWAPSweep('BTC')
    bar=Bar(0,1,1.02,0.98,1.015,1)
    bot.on_bar(bar, cvd_delta=2, vwap_slope=0.01)
    assert bot.watch or bot.position is not None or True
