"""
AgentBase entrypoint for the ZaloPay Stock Intelligence Agent.

Built on the GreenNode AgentBase SDK (`greennode-agentbase`, Starlette-based):
  - GET  /health       -> @app.ping (PingStatus.HEALTHY)
  - POST /invocations  -> @app.entrypoint (trigger the pipeline on demand)
  - GET  /report       -> the generated HTML report (custom route)

Run modes:
  - On-demand: every POST /invocations triggers the pipeline (background thread,
    single-flight) so the request returns immediately.
  - Daily scheduler: if ENABLE_SCHEDULER=true (default), a background thread runs
    the pipeline every day at REPORT_TIME (container TZ = Asia/Ho_Chi_Minh) and
    sends the email report.

Invocation payload (all optional):
  {
    "dry_run":  false,            # true = build report but DON'T send email
    "date":     "2026-06-10",     # single date (YYYY-MM-DD); default today
    "from":     "2026-06-01",     # range start (with optional "to")
    "to":       "2026-06-13",     # range end; default today
    "force":    false,            # run even on weekends/holidays
    "mock_msg": "data/mock_data/data2.msg",  # override ZLP .msg source
    "action":   "status" | "report"          # status/report queries (no run)
  }
"""

import logging
import os
import threading
from datetime import date, datetime

from greennode_agentbase import (
    GreenNodeAgentBaseApp,
    RequestContext,
    PingStatus,
)
from starlette.responses import HTMLResponse, PlainTextResponse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("server")

app = GreenNodeAgentBaseApp()

# Single-flight guard + last-run status -------------------------------------
_run_lock = threading.Lock()
_running = False
_last_run = {"state": "idle", "started_at": None, "finished_at": None,
             "result": None, "error": None, "params": None}


def _parse_date(s):
    return datetime.strptime(s, "%Y-%m-%d").date()


def _execute(params):
    """Run the pipeline in a background thread."""
    global _running
    from scheduler.main_scheduler import run_pipeline, run_pipeline_range

    _last_run.update(state="running",
                     started_at=datetime.utcnow().isoformat() + "Z",
                     finished_at=None, result=None, error=None, params=params)
    try:
        dry_run = bool(params.get("dry_run", False))
        force = bool(params.get("force", False))
        mock_msg = params.get("mock_msg")

        if params.get("from") or params.get("to"):
            start = _parse_date(params["from"]) if params.get("from") else date.today()
            end = _parse_date(params["to"]) if params.get("to") else date.today()
            paths = run_pipeline_range(start_date=start, end_date=end,
                                       dry_run=dry_run, force=force, mock_msg=mock_msg)
            result = {"reports": [str(p) for p in paths], "count": len(paths)}
        else:
            run_date = _parse_date(params["date"]) if params.get("date") else date.today()
            path = run_pipeline(dry_run=dry_run, run_date=run_date,
                                force=force, mock_msg=mock_msg)
            result = {"report": str(path) if path else None}

        _last_run.update(result=result, state="succeeded")
        logger.info("Pipeline run finished: %s", result)
    except Exception as exc:  # noqa: BLE001 - report any failure via status
        _last_run.update(error=str(exc), state="failed")
        logger.exception("Pipeline run failed")
    finally:
        _last_run["finished_at"] = datetime.utcnow().isoformat() + "Z"
        with _run_lock:
            _running = False


def _trigger(params):
    """Start a single-flight pipeline run; returns an ack dict."""
    global _running
    with _run_lock:
        if _running:
            return {"status": "busy",
                    "message": "a pipeline run is already in progress",
                    "last_run": _last_run}
        _running = True
    threading.Thread(target=_execute, args=(params,), daemon=True).start()
    return {"status": "started", "params": params,
            "hint": "poll with {\"action\": \"status\"}"}


def _find_report(date_str=None):
    """Return Path to a report HTML for the given date, or the latest one."""
    import config
    rdir = config.REPORTS_DIR
    if not rdir.exists():
        return None
    if date_str:
        p = rdir / f"report_{date_str}.html"
        return p if p.exists() else None
    reports = sorted(rdir.glob("report_*.html"))
    return reports[-1] if reports else None


@app.entrypoint
def handler(payload: dict, context: RequestContext) -> dict:
    """Trigger the intelligence pipeline on demand (POST /invocations)."""
    params = payload if isinstance(payload, dict) else {}

    action = params.get("action")
    if action == "status":
        return {"status": "ok", "last_run": _last_run}
    if action == "report":
        p = _find_report(params.get("date"))
        if not p:
            return {"status": "not_found",
                    "message": "no report found (run the pipeline first)"}
        return {"status": "ok", "path": str(p),
                "html": p.read_text(encoding="utf-8")}

    return _trigger(params)


@app.ping
def health_check() -> PingStatus:
    return PingStatus.HEALTHY


# ── Custom GET /report route (browser-friendly, auto-regenerates) ───────────
def _wait_page(target_date, busy):
    note = ("A run is in progress — your report will appear automatically."
            if busy else
            "Generating the report now (scrape → analyse → Qwen → build, ~2–3 min).")
    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta http-equiv="refresh" content="6">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Generating report — {target_date}</title></head>
<body style="margin:0;font-family:'Segoe UI',Arial,sans-serif;background:#eef3fb;color:#0b1f3a">
<div style="max-width:520px;margin:64px auto;background:#fff;border:1px solid #e3eaf5;border-radius:16px;
            padding:30px;text-align:center;box-shadow:0 6px 24px rgba(16,42,90,.06)">
  <div style="width:46px;height:46px;border:4px solid #cfe0ff;border-top-color:#0068ff;border-radius:50%;
              margin:0 auto 18px;animation:s 0.9s linear infinite"></div>
  <h2 style="margin:0 0 6px;color:#0068ff;font-size:18px">Generating report for {target_date}</h2>
  <p style="margin:0;color:#5b6b85;font-size:14px">{note}</p>
  <p style="margin:14px 0 0;color:#9aa7bd;font-size:12px">This page refreshes automatically.</p>
</div>
<style>@keyframes s{{to{{transform:rotate(360deg)}}}}</style>
</body></html>"""


async def report_route(request):
    date_str = request.query_params.get("date")
    p = _find_report(date_str)
    if p:
        return HTMLResponse(p.read_text(encoding="utf-8"))
    # Missing: kick off generation for this date (single-flight), show a
    # self-refreshing waiting page that swaps in the report once it's ready.
    target = date_str or date.today().isoformat()
    ack = _trigger({"date": target, "dry_run": True, "force": True})
    busy = ack.get("status") == "busy"
    return HTMLResponse(_wait_page(target, busy), status_code=200)


app.add_route("/report", report_route, methods=["GET"])


# ── GET /summary — accumulated totals over a window ─────────────────────────
async def summary_route(request):
    import config
    from datetime import timedelta
    from data_processor.db_manager import DBManager
    from report_writer.report_builder import build_accumulated_summary

    q = request.query_params
    db = DBManager()

    if q.get("to"):
        end = _parse_date(q["to"])
    else:
        ld = db.latest_date()
        end = _parse_date(ld) if ld else date.today()
    if q.get("from"):
        start = _parse_date(q["from"])
    else:
        try:
            days = max(1, int(q.get("days", "7")))
        except ValueError:
            days = 7
        start = end - timedelta(days=days - 1)

    df = db.read_range(start.isoformat(), end.isoformat())
    if df is None or df.empty:
        # No data yet (fresh container) — populate via a run, show waiting page.
        ack = _trigger({"date": end.isoformat(), "dry_run": True, "force": True})
        return HTMLResponse(_wait_page(f"{start} → {end}",
                                       ack.get("status") == "busy"))
    return HTMLResponse(build_accumulated_summary(start, end, df))


app.add_route("/summary", summary_route, methods=["GET"])


# ── Browser landing page at GET / ───────────────────────────────────────────
_INDEX_HTML = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ZaloPay · Stock Intelligence</title>
<style>
 :root{--zp:#0068ff;--zp2:#00b9f1;--ink:#0b1f3a;--mut:#5b6b85;--bg:#eef3fb;--line:#e3eaf5;--ok:#16a34a;--warn:#d97706;--err:#dc2626}
 *{box-sizing:border-box} body{margin:0;font-family:'Segoe UI',Roboto,Arial,sans-serif;background:var(--bg);color:var(--ink)}
 .top{background:linear-gradient(120deg,#0050d8 0%,var(--zp) 45%,var(--zp2) 100%);color:#fff;padding:0}
 .bar{max-width:1000px;margin:0 auto;display:flex;align-items:center;gap:12px;padding:16px 20px}
 .logo{width:40px;height:40px;border-radius:11px;background:#fff;display:grid;place-items:center;font-weight:900;color:var(--zp);font-size:22px;box-shadow:0 4px 14px rgba(0,0,0,.18)}
 .brand b{font-size:18px;letter-spacing:.2px} .brand div{font-size:12px;opacity:.9}
 .live{margin-left:auto;display:flex;align-items:center;gap:7px;font-size:13px;background:rgba(255,255,255,.16);padding:6px 12px;border-radius:999px}
 .dot{width:9px;height:9px;border-radius:50%;background:#9aa7bd} .dot.on{background:#37e07a;box-shadow:0 0 0 4px rgba(55,224,122,.25)}
 .hero{max-width:1000px;margin:0 auto;padding:18px 20px 6px} .hero h1{font-size:22px;margin:6px 0} .hero p{color:var(--mut);margin:0;font-size:14px}
 .wrap{max-width:1000px;margin:0 auto;padding:14px 20px 40px;display:grid;grid-template-columns:340px 1fr;gap:18px}
 @media(max-width:820px){.wrap{grid-template-columns:1fr}}
 .card{background:#fff;border:1px solid var(--line);border-radius:16px;padding:18px;box-shadow:0 6px 24px rgba(16,42,90,.06)}
 .card h3{margin:0 0 12px;font-size:15px;color:var(--zp)}
 label{display:block;font-size:12px;font-weight:600;color:var(--mut);margin:12px 0 5px;text-transform:uppercase;letter-spacing:.04em}
 input[type=date],input[type=text]{width:100%;padding:10px 12px;border:1px solid var(--line);border-radius:10px;font-size:14px;background:#fbfdff}
 .row{display:flex;align-items:center;gap:9px;margin:10px 0;font-size:14px;font-weight:500;color:var(--ink)}
 .switch{position:relative;width:42px;height:24px;flex:0 0 auto} .switch input{opacity:0;width:0;height:0}
 .sl{position:absolute;inset:0;background:#cbd6ea;border-radius:999px;transition:.2s} .sl:before{content:'';position:absolute;width:18px;height:18px;left:3px;top:3px;background:#fff;border-radius:50%;transition:.2s}
 .switch input:checked+.sl{background:var(--zp)} .switch input:checked+.sl:before{transform:translateX(18px)}
 .btn{width:100%;border:0;border-radius:12px;padding:13px;font-size:15px;font-weight:700;cursor:pointer;margin-top:14px;transition:.15s}
 .btn.primary{background:linear-gradient(120deg,var(--zp),var(--zp2));color:#fff;box-shadow:0 8px 20px rgba(0,104,255,.32)} .btn.primary:hover{filter:brightness(1.05)}
 .btn.ghost{background:#eef3fb;color:var(--zp)} .btn:disabled{opacity:.55;cursor:not-allowed}
 .btns2{display:flex;gap:10px} .btns2 .btn{margin-top:10px}
 .status{display:flex;align-items:center;gap:10px;font-size:14px;margin-top:6px}
 .pill{font-size:12px;font-weight:700;padding:4px 11px;border-radius:999px}
 .pill.idle{background:#eef1f6;color:#64748b}.pill.running{background:#e0edff;color:var(--zp)}.pill.succeeded{background:#dcfce7;color:var(--ok)}.pill.failed{background:#fee2e2;color:var(--err)}
 .spin{width:15px;height:15px;border:2.5px solid #cfe0ff;border-top-color:var(--zp);border-radius:50%;animation:s .8s linear infinite;display:none}@keyframes s{to{transform:rotate(360deg)}}
 .meta{font-size:12px;color:var(--mut);margin-top:8px;line-height:1.6}
 .repwrap{padding:0;overflow:hidden;display:flex;flex-direction:column;min-height:520px}
 .rephead{display:flex;align-items:center;gap:10px;padding:14px 18px;border-bottom:1px solid var(--line)} .rephead h3{margin:0}
 .open{margin-left:auto;font-size:13px;color:var(--zp);text-decoration:none;font-weight:600}
 iframe{border:0;width:100%;flex:1;min-height:520px;background:#fff}
 .empty{flex:1;display:grid;place-items:center;color:var(--mut);text-align:center;padding:30px;font-size:14px}
 .chip{display:inline-block;background:#eef3fb;color:var(--zp);font-size:11px;font-weight:700;padding:3px 9px;border-radius:999px;margin-top:6px}
 .foot{max-width:1000px;margin:0 auto;padding:0 20px 30px;color:var(--mut);font-size:12px}
</style></head><body>
<div class="top"><div class="bar">
  <div class="logo">Z</div>
  <div class="brand"><b>ZaloPay</b><div>Stock Intelligence</div></div>
  <div class="live"><span class="dot" id="hdot"></span><span id="htxt">checking…</span></div>
</div></div>

<div class="hero">
  <h1>Daily Market Intelligence</h1>
  <p>Market vs ZaloPay performance, analysed and summarised by <b>Qwen</b>. Runs on demand here, and automatically every day at 08:00 (VN).</p>
</div>

<div class="wrap">
  <div class="card">
    <h3>⚙️ Generate a report</h3>
    <label>Report date</label>
    <input type="date" id="date">
    <div class="row"><label class="switch"><input type="checkbox" id="dry" checked><span class="sl"></span></label> Dry run <span style="color:var(--mut);font-weight:400">(don't send email)</span></div>
    <div class="row"><label class="switch"><input type="checkbox" id="force" checked><span class="sl"></span></label> Force <span style="color:var(--mut);font-weight:400">(run on holidays/weekends)</span></div>
    <button class="btn primary" id="runbtn" onclick="run()">▶  Run pipeline</button>
    <div class="btns2"><button class="btn ghost" onclick="refresh()">↻ Status</button><button class="btn ghost" onclick="loadReport()">📄 View report</button></div>
    <label>Accumulate over</label>
    <select id="period" style="width:100%;padding:10px 12px;border:1px solid var(--line);border-radius:10px;font-size:14px;background:#fbfdff">
      <option value="5">Last 5 days</option>
      <option value="7" selected>Last 7 days</option>
      <option value="14">Last 14 days</option>
      <option value="30">Last 30 days</option>
    </select>
    <button class="btn ghost" style="margin-top:10px" onclick="loadSummary()">Σ  Accumulated summary</button>
    <hr style="border:0;border-top:1px solid var(--line);margin:16px 0">
    <div class="status"><div class="spin" id="spin"></div><span class="pill idle" id="pill">idle</span></div>
    <div class="meta" id="meta">No run yet. Pick a date and press <b>Run pipeline</b>.</div>
  </div>

  <div class="card repwrap">
    <div class="rephead"><h3>📈 Report</h3><a class="open" id="open" href="#" target="_blank" style="display:none">Open in new tab ↗</a></div>
    <div class="empty" id="empty">Your generated report will appear here.<br><span class="chip">tip: run a date, then it loads automatically</span></div>
    <iframe id="rep" style="display:none"></iframe>
  </div>
</div>
<div class="foot">Powered by GreenNode AgentBase · Insights by Qwen 3.5 · Endpoints: <code>/health</code> · <code>/invocations</code> · <code>/report</code></div>

<script>
const $=id=>document.getElementById(id);
let pollTimer=null;
function setPill(s){const p=$('pill');p.className='pill '+s;p.textContent=s;$('spin').style.display=(s==='running')?'inline-block':'none';}
async function post(b){const r=await fetch('/invocations',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)});return r.json();}
function fmt(t){return t?new Date(t).toLocaleString():'—';}
async function health(){try{const r=await fetch('/health');const ok=r.ok;$('hdot').className='dot'+(ok?' on':'');$('htxt').textContent=ok?'live':'down';}catch(e){$('hdot').className='dot';$('htxt').textContent='down';}}
function dateVal(){return $('date').value||undefined;}
async function run(){
  $('runbtn').disabled=true;setPill('running');$('meta').textContent='Starting pipeline… this takes ~2–3 minutes (scrape → analyse → Qwen → report).';
  try{const r=await post({date:dateVal(),dry_run:$('dry').checked,force:$('force').checked});
    if(r.status==='busy'){$('meta').textContent='A run is already in progress — watching it.';}
    startPoll();
  }catch(e){setPill('failed');$('meta').textContent='Error: '+e;$('runbtn').disabled=false;}
}
function startPoll(){clearInterval(pollTimer);pollTimer=setInterval(refresh,6000);refresh();}
async function refresh(){
  try{const r=await post({action:'status'});const lr=r.last_run||{};setPill(lr.state||'idle');
    let m='State: <b>'+(lr.state||'idle')+'</b>';
    if(lr.started_at)m+=' · started '+fmt(lr.started_at);
    if(lr.finished_at)m+=' · finished '+fmt(lr.finished_at);
    if(lr.error)m+='<br><span style="color:var(--err)">'+lr.error+'</span>';
    if(lr.result&&lr.result.report)m+='<br>Report: '+lr.result.report;
    $('meta').innerHTML=m;
    if(lr.state==='succeeded'||lr.state==='failed'){clearInterval(pollTimer);$('runbtn').disabled=false;if(lr.state==='succeeded')loadReport();}
  }catch(e){}
}
function loadReport(){
  const d=dateVal();const url='/report'+(d?('?date='+encodeURIComponent(d)):'');
  const f=$('rep');f.src=url;f.style.display='block';$('empty').style.display='none';
  const o=$('open');o.href=url;o.style.display='inline';
}
function loadSummary(){
  const url='/summary?days='+encodeURIComponent($('period').value);
  const f=$('rep');f.src=url;f.style.display='block';$('empty').style.display='none';
  const o=$('open');o.href=url;o.style.display='inline';
}
// init: default date = today, check health, load latest report if any
(function(){const t=new Date();$('date').value=t.toISOString().slice(0,10);health();setInterval(health,15000);refresh();})();
</script>
</body></html>"""


async def index_route(request):
    return HTMLResponse(_INDEX_HTML)


app.add_route("/", index_route, methods=["GET"])


# ── Daily scheduler thread ──────────────────────────────────────────────────
def _scheduler_loop():
    """Run the pipeline daily at REPORT_TIME (container-local = VN time)."""
    import time
    import schedule
    import config

    hh, mm = config.REPORT_TIME.split(":")
    at = f"{int(hh):02d}:{int(mm):02d}"
    logger.info("Daily scheduler armed for %s %s (sends email)", at, config.TIMEZONE)
    schedule.every().day.at(at).do(lambda: _trigger({"dry_run": False}))
    while True:
        try:
            schedule.run_pending()
        except Exception:  # noqa: BLE001 - never let the scheduler kill the server
            logger.exception("scheduler tick failed")
        time.sleep(30)


def _maybe_start_scheduler():
    if os.getenv("ENABLE_SCHEDULER", "true").lower() not in ("1", "true", "yes"):
        logger.info("Daily scheduler disabled (ENABLE_SCHEDULER != true)")
        return
    try:
        threading.Thread(target=_scheduler_loop, daemon=True).start()
    except Exception:  # noqa: BLE001 - health must stay up regardless
        logger.exception("failed to start scheduler thread")


_maybe_start_scheduler()


if __name__ == "__main__":
    logger.info("Starting AgentBase app on port 8080")
    app.run(port=8080, host="0.0.0.0")
