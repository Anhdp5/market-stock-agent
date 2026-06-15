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


# ── Custom GET /report route (browser-friendly) ─────────────────────────────
async def report_route(request):
    date_str = request.query_params.get("date")
    p = _find_report(date_str)
    if not p:
        return PlainTextResponse(
            "No report found. Run the pipeline first via POST /invocations.",
            status_code=404)
    return HTMLResponse(p.read_text(encoding="utf-8"))


app.add_route("/report", report_route, methods=["GET"])


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
