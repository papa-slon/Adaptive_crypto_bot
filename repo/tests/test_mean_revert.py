
from agents.mean_revert import MeanRevert, Bar
def test_mr_no_signal_initial():
    bot=MeanRevert('BTC')
    for i in range(500):
        bot.on_bar(Bar(i,1,1,1,1,1), cvd_delta=0)
    assert bot.position is None
