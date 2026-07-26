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
import base64
import hmac
import json
import os
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from algo_engine.carry_bot.secrets_store import SecretsStore, SecretsUnavailable
from algo_engine.carry_bot.state import read_history, read_state
from algo_engine.carry_bot.venues import venue_choices

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


# --------------------------------------------------------------- settings UI
def _settings_page(cfg: dict, venues: list[str], message: str = "", error: str = "") -> str:
    """Credential + sizing form. Secrets are WRITE-ONLY: the current values are
    shown only as fingerprints and an empty field means "keep what is stored"."""
    opts = "".join(
        f'<option value="{v}"{" selected" if cfg.get("venue") == v else ""}>{v}</option>'
        for v in venues)
    banner = ""
    if message:
        banner = f'<div class="card" style="border-color:#16c784"><b>{message}</b></div>'
    elif error:
        banner = f'<div class="card" style="border-color:#ea3943"><b>{error}</b></div>'
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>CARRY · settings</title>
<style>
 body{{background:#080b11;color:#d8e2ee;font-family:'JetBrains Mono',Consolas,monospace;
      font-size:13px;margin:0}}
 header{{padding:12px 18px;border-bottom:1px solid #1c2836}}
 .mark{{font-weight:700;letter-spacing:.22em}}
 a{{color:#3da9fc}}
 .wrap{{max-width:620px;margin:22px auto;padding:0 16px;display:grid;gap:14px}}
 .card{{background:#0e151f;border:1px solid #1c2836;border-radius:10px;padding:16px}}
 label{{display:block;margin:12px 0 4px;color:#6b7d93;font-size:11px;
        letter-spacing:.12em;text-transform:uppercase}}
 input,select{{width:100%;padding:9px 10px;background:#121b27;color:#d8e2ee;
        border:1px solid #1c2836;border-radius:6px;font-family:inherit;font-size:13px}}
 button{{margin-top:16px;padding:10px 18px;background:#16c784;color:#04140d;border:0;
         border-radius:6px;font-weight:700;font-family:inherit;cursor:pointer}}
 .muted{{color:#6b7d93;font-size:11.5px;line-height:1.6}}
 .row{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px}}
</style></head><body>
<header><span class="mark">◢ CARRY</span> · settings &nbsp; <a href="/">← dashboard</a></header>
<div class="wrap">
{banner}
<form class="card" method="post" action="/settings">
  <label>Exchange</label>
  <select name="venue">{opts}</select>

  <label>API key</label>
  <input name="api_key" autocomplete="off" placeholder="{cfg.get('api_key') or 'not set'}">
  <label>API secret</label>
  <input name="api_secret" type="password" autocomplete="off"
         placeholder="{cfg.get('api_secret') or 'not set'}">
  <div class="muted">Leave a field blank to keep the stored value. Stored values are
  never sent back to the browser — only the fingerprint above.</div>

  <div class="row">
    <div><label>Capital (USDT)</label>
      <input name="capital" value="{cfg.get('capital', 200)}"></div>
    <div><label>Slots</label>
      <input name="slots" value="{cfg.get('slots', 3)}"></div>
    <div><label>Leverage</label>
      <input name="leverage" value="{cfg.get('leverage', 1)}"></div>
  </div>
  <button type="submit">Save</button>
</form>
<div class="card muted">
  Credentials are encrypted on this host with a key derived from
  <code>BOT_ADMIN_PASSWORD</code>, which is never written to disk — a stolen disk
  image or backup is useless without it. It does <b>not</b> protect against an
  attacker who already controls this running host, so use an exchange key with
  <b>trading only, no withdrawal</b>, ideally IP-restricted to this server.
  Restart the bot for a change to take effect.
</div>
</div></body></html>"""


def _admin_password() -> str:
    return os.environ.get("BOT_ADMIN_PASSWORD", "")


def _authorised(header: str | None) -> bool:
    """HTTP Basic against BOT_ADMIN_PASSWORD (any username), compared in
    constant time. No password configured => the settings UI stays closed."""
    expected = _admin_password()
    if not expected or not header or not header.startswith("Basic "):
        return False
    try:
        raw = base64.b64decode(header[6:]).decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return False
    _, _, supplied = raw.partition(":")
    return hmac.compare_digest(supplied, expected)


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ---- auth ----
    def _deny(self) -> None:
        body = b"settings require BOT_ADMIN_PASSWORD"
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="carry-bot settings"')
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _guard(self) -> bool:
        if _authorised(self.headers.get("Authorization")):
            return True
        self._deny()
        return False

    def do_GET(self):  # noqa: N802
        if self.path.startswith("/api/state"):
            self._send(200, json.dumps(read_state() or {}).encode(), "application/json")
        elif self.path.startswith("/api/history"):
            self._send(200, json.dumps(read_history(limit=1500)).encode(), "application/json")
        elif self.path.startswith("/settings"):
            if not self._guard():
                return
            store = SecretsStore()
            page = _settings_page(store.redacted(), venue_choices())
            self._send(200, page.encode(), "text/html; charset=utf-8")
        elif self.path in ("/", "/index.html"):
            self._send(200, _PAGE.encode(), "text/html; charset=utf-8")
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self):  # noqa: N802
        if not self.path.startswith("/settings"):
            self._send(404, b"not found", "text/plain")
            return
        if not self._guard():
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        raw = self.rfile.read(min(length, 64_000)).decode("utf-8", "replace")
        form = {k: v[0] for k, v in urllib.parse.parse_qs(raw, keep_blank_values=True).items()}

        store = SecretsStore()
        message = error = ""
        try:
            current = store.load() if store.exists() else {}
            merged = dict(current)
            merged["venue"] = form.get("venue") or current.get("venue") or "bybit-demo"
            # a blank secret field means "keep what is stored"
            for field in ("api_key", "api_secret"):
                supplied = (form.get(field) or "").strip()
                if supplied:
                    merged[field] = supplied
            for field, cast in (("capital", float), ("slots", int), ("leverage", float)):
                try:
                    merged[field] = cast(form.get(field) or current.get(field) or 0)
                except (TypeError, ValueError):
                    pass
            if int(merged.get("slots") or 0) < 2:
                raise ValueError("slots must be 2 or more: a single-slot carry "
                                 "backtested negative at every leverage")
            store.save(merged)
            message = "Saved. Restart the bot to apply."
        except SecretsUnavailable as exc:
            error = str(exc)
        except ValueError as exc:
            error = str(exc)
        except Exception as exc:  # noqa: BLE001 — never leak a stack trace to the browser
            error = f"could not save: {type(exc).__name__}"

        page = _settings_page(store.redacted(), venue_choices(), message=message, error=error)
        self._send(200, page.encode(), "text/html; charset=utf-8")

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
