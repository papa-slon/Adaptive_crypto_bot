"""Zero-dependency monitoring dashboard for the carry bot.

Serves one dark "terminal" page plus a JSON API over the state the live loop
(single symbol) or the autopilot (multi-slot portfolio) writes. stdlib only.

    python -m algo_engine.carry_bot.dashboard --port 8080

Security: this binds 0.0.0.0 by default so it is reachable from a browser on
another machine, and it has NO authentication — it exposes balances, position
sizes and P&L (never API keys). On a public server either keep it on
127.0.0.1 and reach it through an SSH tunnel, or put it behind a reverse proxy
with auth. Pass --host 127.0.0.1 to make that the default.
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
    --bg:#080b11; --panel:#0e151f; --panel2:#121b27; --line:#1c2836;
    --txt:#d8e2ee; --dim:#6b7d93; --accent:#3da9fc; --green:#16c784; --red:#ea3943;
    --amber:#f5a623; --mono:'JetBrains Mono','SFMono-Regular',Consolas,monospace;
  }
  *{box-sizing:border-box} html,body{margin:0;height:100%}
  body{background:var(--bg);color:var(--txt);font-family:var(--mono);font-size:13px}
  header{display:flex;align-items:center;gap:14px;padding:12px 18px;
         border-bottom:1px solid var(--line);background:linear-gradient(180deg,#0e151f,#080b11);
         position:sticky;top:0;z-index:5}
  header .mark{font-weight:700;letter-spacing:.22em;color:#fff;font-size:13px}
  header .sym{color:var(--accent);font-weight:700}
  .pill{margin-left:auto;display:flex;align-items:center;gap:8px;font-size:11px;color:var(--dim)}
  .dot{width:9px;height:9px;border-radius:50%;background:var(--dim);box-shadow:0 0 8px currentColor}
  .dot.live{background:var(--green)} .dot.flat{background:var(--amber)} .dot.stale{background:var(--red)}
  .wrap{padding:16px;display:grid;gap:14px;grid-template-columns:repeat(4,1fr);
        max-width:1240px;margin:0 auto}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
  .card .k{color:var(--dim);font-size:10.5px;letter-spacing:.14em;text-transform:uppercase}
  .card .v{font-size:24px;margin-top:6px;font-weight:600}
  .v.green{color:var(--green)} .v.red{color:var(--red)} .v.amber{color:var(--amber)}
  .v.big{font-size:30px}
  .sub{color:var(--dim);font-size:11px;margin-top:3px}
  .span2{grid-column:span 2} .span4{grid-column:span 4}
  canvas{width:100%;height:210px;display:block}
  table{width:100%;border-collapse:collapse;font-size:12px}
  th,td{text-align:left;padding:7px 6px;border-bottom:1px solid var(--line);white-space:nowrap}
  th{color:var(--dim);font-weight:500;font-size:10.5px;letter-spacing:.1em;text-transform:uppercase}
  td.r,th.r{text-align:right}
  .scroll{overflow-x:auto}
  .feed{max-height:220px;overflow:auto;font-size:12px;line-height:1.85}
  .feed .t{color:var(--dim)} .feed b{color:var(--accent);font-weight:600}
  .bar{height:8px;background:var(--panel2);border-radius:6px;overflow:hidden;margin-top:8px}
  .bar>i{display:block;height:100%;background:linear-gradient(90deg,var(--red),var(--amber),var(--green))}
  .muted{color:var(--dim)}
  .tag{display:inline-block;padding:1px 7px;border-radius:99px;font-size:10px;
       border:1px solid var(--line);color:var(--dim)}
  @media(max-width:860px){.wrap{grid-template-columns:repeat(2,1fr)}.span4{grid-column:span 2}}
</style></head>
<body>
<header>
  <span class="mark">◢ CARRY</span><span class="sym" id="sym">—</span>
  <span class="tag" id="mode">—</span>
  <span class="pill"><span class="dot" id="dot"></span><span id="statetxt">connecting…</span>
  <span id="uptime"></span></span>
</header>
<div class="wrap">
  <div class="card"><div class="k">Realised yield (annualised)</div>
    <div class="v big" id="apr">—</div><div class="sub" id="aprsub">from funding actually booked</div></div>
  <div class="card"><div class="k">Funding collected</div>
    <div class="v" id="funding">—</div><div class="sub" id="fundsub"></div></div>
  <div class="card"><div class="k">Equity</div>
    <div class="v" id="equity">—</div><div class="sub" id="startEq"></div></div>
  <div class="card"><div class="k">P&amp;L</div>
    <div class="v" id="pnl">—</div><div class="sub" id="pnlpct"></div></div>

  <div class="card span2"><div class="k">Equity curve</div><canvas id="chart"></canvas></div>
  <div class="card span2"><div class="k" id="posTitle">Positions</div>
    <div class="scroll"><table id="postbl">
      <thead><tr><th>Symbol</th><th class="r">Funding /8h</th><th class="r">~APR</th>
      <th class="r">Spot</th><th class="r">Perp</th><th class="r">Margin</th><th class="r">Held</th></tr></thead>
      <tbody id="posbody"><tr><td colspan="7" class="muted">no open slots</td></tr></tbody>
    </table></div>
    <div class="sub" id="cfg" style="margin-top:10px"></div>
  </div>

  <div class="card span4"><div class="k">Activity</div>
    <div class="feed" id="feed"><span class="muted">waiting for the bot…</span></div></div>
</div>
<script>
const $=id=>document.getElementById(id);
const txt=(id,v)=>{$(id).textContent=v};
const fmt=(x,d=2)=>x==null?'—':Number(x).toLocaleString('en-US',{minimumFractionDigits:d,maximumFractionDigits:d});
function dur(s){if(s==null)return'';const d=Math.floor(s/86400),h=Math.floor(s%86400/3600),m=Math.floor(s%3600/60);
  return d?`${d}d ${h}h`:(h?`${h}h ${m}m`:`${m}m`)}
function drawChart(hist){
  const c=$('chart'),dpr=devicePixelRatio||1,W=c.clientWidth,H=c.clientHeight;
  c.width=W*dpr;c.height=H*dpr;const g=c.getContext('2d');g.scale(dpr,dpr);g.clearRect(0,0,W,H);
  if(!hist||hist.length<2){g.fillStyle='#6b7d93';g.font='12px monospace';g.fillText('collecting data…',12,22);return}
  const ys=hist.map(p=>p.equity),min=Math.min(...ys),max=Math.max(...ys),pad=(max-min)*0.12||Math.abs(max)*0.001||0.001;
  const lo=min-pad,hi=max+pad,X=i=>i/(hist.length-1)*(W-8)+4,Y=v=>H-8-(v-lo)/(hi-lo)*(H-16);
  g.strokeStyle='#1c2836';g.lineWidth=1;
  for(let k=0;k<=3;k++){const y=8+k*(H-16)/3;g.beginPath();g.moveTo(0,y);g.lineTo(W,y);g.stroke();}
  const up=ys[ys.length-1]>=ys[0];g.strokeStyle=up?'#16c784':'#ea3943';g.lineWidth=1.8;g.beginPath();
  hist.forEach((p,i)=>{const x=X(i),y=Y(p.equity);i?g.lineTo(x,y):g.moveTo(x,y)});g.stroke();
  const grd=g.createLinearGradient(0,0,0,H);
  grd.addColorStop(0,(up?'rgba(22,199,132,':'rgba(234,57,57,')+'0.18)');grd.addColorStop(1,'rgba(0,0,0,0)');
  g.lineTo(X(hist.length-1),H);g.lineTo(X(0),H);g.closePath();g.fillStyle=grd;g.fill();
}
function renderSlots(s){
  const body=$('posbody');
  if(s.kind==='portfolio'){
    $('posTitle').textContent=`Slots ${s.slots_open||0}/${s.slots_target||0}`;
    const rows=(s.slots||[]).map(x=>`<tr>
      <td><b>${x.symbol}</b></td>
      <td class="r">${x.funding_rate==null?'—':(x.funding_rate*100>=0?'+':'')+fmt(x.funding_rate*100,4)+'%'}</td>
      <td class="r">${x.ann_pct==null?'—':(x.ann_pct>=0?'+':'')+fmt(x.ann_pct,1)+'%'}</td>
      <td class="r">${fmt(x.spot_qty,5)}</td><td class="r">${fmt(x.perp_qty,5)}</td>
      <td class="r">${x.margin_ratio==null?'—':fmt(x.margin_ratio*100,1)+'%'}</td>
      <td class="r">${x.held_minutes==null?'—':dur(x.held_minutes*60)}</td></tr>`).join('');
    body.innerHTML=rows||'<tr><td colspan="7" class="muted">scanning for a payer…</td></tr>';
    $('cfg').textContent=`capital ${fmt(s.capital,0)} USDT · ${fmt(s.leverage,0)}x · `
      +`notional/slot ${fmt(s.notional_per_slot,2)}`;
  }else{
    $('posTitle').textContent='Position';
    body.innerHTML=`<tr><td><b>${s.symbol||'—'}</b></td><td class="r">—</td><td class="r">—</td>
      <td class="r">${fmt(s.spot_qty,5)}</td><td class="r">${fmt(s.perp_qty,5)}</td>
      <td class="r">${s.margin_ratio==null?'—':fmt(s.margin_ratio*100,1)+'%'}</td>
      <td class="r">${dur(s.uptime_seconds)}</td></tr>`;
    $('cfg').textContent=`notional ${fmt(s.notional,2)} · ${fmt(s.leverage,0)}x · errors ${s.errors||0}`;
  }
}
async function tick(){
  let s,h;
  try{
    s=await (await fetch('/api/state',{cache:'no-store'})).json();
    h=await (await fetch('/api/history',{cache:'no-store'})).json();
  }catch(e){txt('statetxt','dashboard offline');$('dot').className='dot stale';return}
  if(!s||!s.ts){txt('statetxt','bot not started');$('dot').className='dot stale';return}
  const stale=(Date.now()-Date.parse(s.ts))>180000;
  $('dot').className='dot '+(stale?'stale':(s.state==='HOLD'?'live':'flat'));
  txt('statetxt',stale?'STALE':(s.state==='HOLD'?'LIVE':s.state));
  txt('sym',s.kind==='portfolio'?`${s.slots_open||0} slots`:(s.symbol||'—'));
  txt('mode',(s.mode||'').toUpperCase());
  txt('uptime',' · '+dur(s.uptime_seconds));

  // realised annualised yield on deployed capital, from booked funding
  const base=s.kind==='portfolio'?s.capital:(s.start_equity||s.notional);
  const days=(s.uptime_seconds||0)/86400;
  const fc=s.funding_collected;
  if(fc!=null&&base&&days>0.02){
    const apr=(fc/base)*(365/days)*100;
    txt('apr',(apr>=0?'+':'')+fmt(apr,2)+'%');
    $('apr').className='v big '+(apr>=0?'green':'red');
    txt('aprsub',`from ${fmt(fc,4)} USDT booked over ${dur(s.uptime_seconds)}`);
  }else{txt('apr','—');$('apr').className='v big';txt('aprsub','needs ~30min of funding data')}

  txt('funding',fc==null?'n/a':fmt(fc,4));
  txt('fundsub',base?`on ${fmt(base,0)} USDT capital`:'');
  txt('equity',fmt(s.equity,4));
  txt('startEq',s.start_equity?('start '+fmt(s.start_equity,4)):'');
  const pnl=s.pnl;
  txt('pnl',pnl==null?'—':(pnl>=0?'+':'')+fmt(pnl,4));
  $('pnl').className='v '+(pnl==null?'':pnl>=0?'green':'red');
  txt('pnlpct',s.pnl_pct==null?'':((s.pnl_pct>=0?'+':'')+fmt(s.pnl_pct,3)+'%'));

  renderSlots(s);
  $('feed').innerHTML=(s.actions||[]).map(a=>`<div><b>›</b> ${a}</div>`).join('')
    ||'<span class="muted">no actions yet</span>';
  drawChart(h);
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
    ap.add_argument("--host", default="0.0.0.0",
                    help="use 127.0.0.1 on a public server and tunnel in over SSH")
    ap.add_argument("--port", type=int, default=8080)
    args = ap.parse_args()
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    if args.host == "0.0.0.0":
        print("WARNING: dashboard has no auth and is reachable from the network. "
              "Prefer --host 127.0.0.1 + an SSH tunnel on a public server.")
    print(f"carry dashboard on http://{args.host}:{args.port}  (Ctrl-C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
