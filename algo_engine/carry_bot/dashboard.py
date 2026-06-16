"""Zero-dependency monitoring dashboard for the carry bot.

Serves one polished dark "terminal" page (Bloomberg / dYdX vibe) plus a JSON
API that reads the state + history the live loop writes. stdlib only.

    python -m algo_engine.carry_bot.dashboard --port 8080
    # open http://<server-ip>:8080
"""
from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from algo_engine.carry_bot.state import read_history, read_state

_PAGE = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>CARRY · terminal</title>
<style>
  :root{
    --bg:#0a0e14; --panel:#0f1620; --panel2:#121b27; --line:#1d2a3a;
    --txt:#d7e0ea; --dim:#6b7d93; --accent:#3da9fc; --green:#16c784; --red:#ea3943;
    --amber:#f5a623; --mono:'JetBrains Mono','SFMono-Regular',Consolas,monospace;
  }
  *{box-sizing:border-box} html,body{margin:0;height:100%}
  body{background:var(--bg);color:var(--txt);font-family:var(--mono);font-size:13px}
  header{display:flex;align-items:center;gap:14px;padding:12px 18px;border-bottom:1px solid var(--line);background:linear-gradient(180deg,#0f1620,#0a0e14)}
  header .mark{font-weight:700;letter-spacing:.22em;color:#fff;font-size:13px}
  header .sym{color:var(--accent);font-weight:700}
  .pill{margin-left:auto;display:flex;align-items:center;gap:8px;font-size:11px;color:var(--dim)}
  .dot{width:9px;height:9px;border-radius:50%;background:var(--dim);box-shadow:0 0 8px currentColor}
  .dot.live{background:var(--green)} .dot.flat{background:var(--amber)} .dot.stale{background:var(--red)}
  .wrap{padding:16px;display:grid;gap:14px;grid-template-columns:repeat(4,1fr);max-width:1200px;margin:0 auto}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
  .card .k{color:var(--dim);font-size:10.5px;letter-spacing:.14em;text-transform:uppercase}
  .card .v{font-size:24px;margin-top:6px;font-weight:600;letter-spacing:.01em}
  .v.green{color:var(--green)} .v.red{color:var(--red)} .v.amber{color:var(--amber)}
  .sub{color:var(--dim);font-size:11px;margin-top:3px}
  .span2{grid-column:span 2} .span4{grid-column:span 4}
  canvas{width:100%;height:220px;display:block}
  table{width:100%;border-collapse:collapse;font-size:12px}
  th,td{text-align:left;padding:7px 6px;border-bottom:1px solid var(--line)}
  th{color:var(--dim);font-weight:500;font-size:10.5px;letter-spacing:.1em;text-transform:uppercase}
  td.r,th.r{text-align:right}
  .feed{max-height:230px;overflow:auto;font-size:12px;line-height:1.85}
  .feed .t{color:var(--dim)} .feed b{color:var(--accent);font-weight:600}
  .bar{height:8px;background:var(--panel2);border-radius:6px;overflow:hidden;margin-top:8px}
  .bar>i{display:block;height:100%;background:linear-gradient(90deg,var(--red),var(--amber),var(--green))}
  .muted{color:var(--dim)}
</style></head>
<body>
<header>
  <span class="mark">◢ CARRY</span><span class="sym" id="sym">—</span>
  <span class="muted" id="mode">—</span>
  <span class="pill"><span class="dot" id="dot"></span><span id="statetxt">connecting…</span>
  <span id="uptime"></span></span>
</header>
<div class="wrap">
  <div class="card"><div class="k">Equity</div><div class="v" id="equity">—</div><div class="sub" id="startEq"></div></div>
  <div class="card"><div class="k">P&amp;L</div><div class="v" id="pnl">—</div><div class="sub" id="pnlpct"></div></div>
  <div class="card"><div class="k">Funding collected</div><div class="v" id="funding">—</div><div class="sub">short-perp carry</div></div>
  <div class="card"><div class="k">Perp margin ratio</div><div class="v" id="mr">—</div><div class="bar"><i id="mrbar"></i></div></div>

  <div class="card span2"><div class="k">Equity curve</div><canvas id="chart"></canvas></div>
  <div class="card span2">
    <div class="k">Position</div>
    <table id="postbl"><thead><tr><th>Leg</th><th class="r">Qty</th><th class="r">Mark</th><th class="r">Notional</th></tr></thead>
    <tbody><tr><td>Spot (long)</td><td class="r" id="spotq">—</td><td class="r" id="px1">—</td><td class="r" id="spotn">—</td></tr>
    <tr><td>Perp (short)</td><td class="r" id="perpq">—</td><td class="r" id="px2">—</td><td class="r" id="perpn">—</td></tr></tbody></table>
    <div class="sub" id="cfg" style="margin-top:10px"></div>
  </div>

  <div class="card span4"><div class="k">Activity</div><div class="feed" id="feed"><span class="muted">waiting for the bot…</span></div></div>
</div>
<script>
const $=id=>document.getElementById(id);
const fmt=(x,d=2)=>x==null?'—':Number(x).toLocaleString('en-US',{minimumFractionDigits:d,maximumFractionDigits:d});
function dur(s){if(s==null)return'';const h=Math.floor(s/3600),m=Math.floor(s%3600/60);return h?`${h}h ${m}m`:`${m}m`}
function drawChart(hist){
  const c=$('chart'),dpr=devicePixelRatio||1,W=c.clientWidth,H=c.clientHeight;
  c.width=W*dpr;c.height=H*dpr;const g=c.getContext('2d');g.scale(dpr,dpr);g.clearRect(0,0,W,H);
  if(!hist.length){g.fillStyle='#6b7d93';g.fillText('no data yet',12,20);return}
  const ys=hist.map(p=>p.equity),min=Math.min(...ys),max=Math.max(...ys),pad=(max-min)*0.12||0.001;
  const lo=min-pad,hi=max+pad,X=i=>i/(hist.length-1||1)*(W-8)+4,Y=v=>H-8-(v-lo)/(hi-lo)*(H-16);
  g.strokeStyle='#1d2a3a';g.lineWidth=1;for(let k=0;k<=3;k++){const y=8+k*(H-16)/3;g.beginPath();g.moveTo(0,y);g.lineTo(W,y);g.stroke();}
  const up=ys[ys.length-1]>=ys[0];g.strokeStyle=up?'#16c784':'#ea3943';g.lineWidth=1.8;g.beginPath();
  hist.forEach((p,i)=>{const x=X(i),y=Y(p.equity);i?g.lineTo(x,y):g.moveTo(x,y);});g.stroke();
  const grd=g.createLinearGradient(0,0,0,H);grd.addColorStop(0,(up?'rgba(22,199,132,':'rgba(234,57,57,')+'0.18)');grd.addColorStop(1,'rgba(0,0,0,0)');
  g.lineTo(X(hist.length-1),H);g.lineTo(X(0),H);g.closePath();g.fillStyle=grd;g.fill();
}
async function tick(){
  let s,h;
  try{s=await (await fetch('/api/state',{cache:'no-store'})).json();h=await (await fetch('/api/history',{cache:'no-store'})).json();}
  catch(e){$('statetxt').textContent='dashboard offline';$('dot').className='dot stale';return;}
  const st=s&&s.state;
  if(!s){$('statetxt').textContent='bot not started';$('dot').className='dot stale';return;}
  const ageStale=(Date.now()-Date.parse(s.ts))>120000;
  $('dot').className='dot '+(ageStale?'stale':(st==='HOLD'?'live':'flat'));
  $('statetxt').textContent=ageStale?'STALE':(st==='HOLD'?'LIVE':st);
  $('sym').textContent=s.symbol||'—';$('mode').textContent=(s.mode||'').toUpperCase();
  $('uptime').textContent=' · '+dur(s.uptime_seconds);
  $('equity').textContent=fmt(s.equity,4);$('startEq').textContent='start '+fmt(s.start_equity,4);
  const pnl=s.pnl,pos=pnl>=0;$('pnl').textContent=(pnl==null?'—':(pos?'+':'')+fmt(pnl,4));$('pnl').className='v '+(pnl==null?'':pos?'green':'red');
  $('pnlpct').textContent=s.pnl_pct==null?'':((s.pnl_pct>=0?'+':'')+fmt(s.pnl_pct,3)+'%');
  $('funding').textContent=s.funding_collected==null?'n/a':(fmt(s.funding_collected,5));
  const mr=s.margin_ratio;$('mr').textContent=mr==null?'—':fmt(mr*100,1)+'%';
  $('mr').className='v '+(mr==null?'':mr<0.1?'red':mr<0.2?'amber':'green');
  $('mrbar').style.width=Math.max(0,Math.min(100,(mr||0)*100*2))+'%';
  $('spotq').textContent=fmt(s.spot_qty,6);$('perpq').textContent=fmt(s.perp_qty,6);
  $('px1').textContent=$('px2').textContent=fmt(s.price,2);
  $('spotn').textContent=fmt((s.spot_qty||0)*(s.price||0),2);$('perpn').textContent=fmt((s.perp_qty||0)*(s.price||0),2);
  $('cfg').textContent=`notional ${fmt(s.notional,0)} · ${fmt(s.leverage,0)}x · errors ${s.errors||0}`;
  $('feed').innerHTML=(s.actions||[]).map(a=>`<div><b>›</b> ${a}</div>`).join('')||'<span class="muted">no actions yet</span>';
  drawChart(h||[]);
}
tick();setInterval(tick,5000);
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path.startswith("/api/state"):
            self._send(200, json.dumps(read_state() or {}).encode(), "application/json")
        elif self.path.startswith("/api/history"):
            self._send(200, json.dumps(read_history(limit=1500)).encode(), "application/json")
        elif self.path in ("/", "/index.html"):
            self._send(200, _PAGE.encode(), "text/html; charset=utf-8")
        else:
            self._send(404, b"not found", "text/plain")

    def log_message(self, *a):  # silence per-request logging
        return


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8080)
    args = ap.parse_args()
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"carry dashboard on http://{args.host}:{args.port}  (Ctrl-C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
