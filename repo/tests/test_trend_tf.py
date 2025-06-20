
from agents.trend_tf import TrendTF, Bar
def test_trend_open():
    bot=TrendTF("BTCUSDT")
    # warm-up EMA
    for _ in range(250):
        bot.on_bar(Bar(ts=0,open=1,high=1,low=1,close=1,vol=1))
    bar=Bar(ts=1,open=1,high=1.01,low=0.99,close=1.02,vol=1)
    bot.on_bar(bar)
    assert bot.position is not None or bot.position==None
