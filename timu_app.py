"""
Timu App — animated browser UI for the Timu data-extraction agent.
==================================================================

    pip install -r requirements.txt
    python timu_app.py              ->  http://127.0.0.1:7801

Optional AI shaping (the "AI SHAPING" switch in the UI):
    set ANTHROPIC_API_KEY=sk-ant-...        (Windows)
    export ANTHROPIC_API_KEY=sk-ant-...     (macOS / Linux)

Endpoints
---------
GET  /                    the UI (timu_ui.html)
GET  /api/health          engine status + whether an LLM key is present
POST /api/scrape          {targets:[...], query, pages, respect_robots, use_llm}
                          -> NDJSON stream of progress events, final {"event":"report"}
POST /api/download/<fmt>  fmt = json|csv|md|xlsx ; body = the report JSON
POST /api/reset           clears the server-side last-report cache
GET  /api/cache           page-cache stats ; POST /api/cache/clear empties it
"""

from __future__ import annotations

import io
import json
import os
import queue
import threading
import webbrowser
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_file

from timu_engine import (MAX_TARGETS, TIMU_VERSION, TimuConfig, TimuScraper, anthropic_llm,
                         export_csv, export_json, export_markdown, export_xlsx)

HERE = Path(__file__).resolve().parent
UI = HERE / "timu_ui.html"
app = Flask(__name__, static_folder=None)
app.config["JSON_SORT_KEYS"] = False
STATE: dict = {"last_report": None}


@app.get("/")
def index():
    if not UI.exists():
        return ("timu_ui.html not found next to timu_app.py", 500)
    return Response(UI.read_text(encoding="utf-8"), mimetype="text/html")


@app.get("/api/health")
def health():
    caps = {"httpx": False, "playwright": False, "chromium": False}
    try:
        import timu_fetch as tfetch
        caps["httpx"] = tfetch.HAVE_HTTPX
        caps["playwright"] = tfetch.HAVE_PLAYWRIGHT
        caps["chromium"] = tfetch.chromium_available()[0]
    except Exception:
        pass
    return jsonify({"ok": True, "version": TIMU_VERSION, "max_targets": MAX_TARGETS,
                    "llm": bool(os.environ.get("ANTHROPIC_API_KEY")), "caps": caps})


@app.get("/api/cache")
def cache_stats():
    try:
        import timu_fetch as tfetch
        return jsonify(tfetch.PageCache(os.environ.get("TIMU_CACHE", ".timu_cache")).stats())
    except Exception as e:                                          # noqa: BLE001
        return jsonify({"error": f"{e.__class__.__name__}: {e}"}), 500


@app.post("/api/cache/clear")
def cache_clear():
    try:
        import timu_fetch as tfetch
        c = tfetch.PageCache(os.environ.get("TIMU_CACHE", ".timu_cache"))
        c.clear()
        return jsonify({"ok": True, **c.stats()})
    except Exception as e:                                          # noqa: BLE001
        return jsonify({"error": f"{e.__class__.__name__}: {e}"}), 500


@app.post("/api/reset")
def reset():
    STATE["last_report"] = None
    return jsonify({"ok": True})


@app.post("/api/scrape")
def scrape():
    body = request.get_json(silent=True) or {}
    targets = [str(t) for t in (body.get("targets") or []) if str(t).strip()][:MAX_TARGETS]
    query = str(body.get("query") or "")
    if not targets:
        return jsonify({"error": "no targets"}), 400

    render = str(body.get("render") or "auto").lower()
    if render not in ("auto", "http", "browser"):
        render = "auto"
    cfg = TimuConfig(
        max_pages_per_site=max(1, min(int(body.get("pages") or 1), 8)),
        respect_robots=bool(body.get("respect_robots", True)),
        concurrency=min(5, max(1, len(targets))),
        render=render,
        wait_for=(str(body.get("wait_for")).strip() or None) if body.get("wait_for") else None,
        use_cache=bool(body.get("use_cache", True)),
        discover=bool(body.get("discover", True)),
        cache_path=os.environ.get("TIMU_CACHE", ".timu_cache"),
        transport=str(body.get("transport") or "auto"),
    )
    llm_fn = None
    if body.get("use_llm"):
        key = os.environ.get("ANTHROPIC_API_KEY")
        if key:
            llm_fn = anthropic_llm(key, os.environ.get("TIMU_LLM_MODEL", "claude-sonnet-4-5"))

    q: "queue.Queue[dict | None]" = queue.Queue()
    holder: dict = {}

    def worker():
        try:
            rep = TimuScraper(cfg=cfg, llm_fn=llm_fn).run(targets, query, progress=q.put)
            holder["report"] = rep
        except Exception as e:                                   # noqa: BLE001
            holder["error"] = f"{e.__class__.__name__}: {e}"
        finally:
            q.put(None)

    threading.Thread(target=worker, daemon=True).start()

    def stream():
        yield json.dumps({"event": "accepted", "targets": targets}) + "\n"
        while True:
            ev = q.get()
            if ev is None:
                break
            yield json.dumps(ev, default=str) + "\n"
        if "report" in holder:
            STATE["last_report"] = holder["report"]
            yield json.dumps({"event": "report", "report": holder["report"]}, default=str) + "\n"
        else:
            yield json.dumps({"event": "error", "error": holder.get("error", "unknown")}) + "\n"

    return Response(stream(), mimetype="application/x-ndjson",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/download/<fmt>")
def download(fmt: str):
    rep = request.get_json(silent=True) or STATE.get("last_report")
    if not rep:
        return jsonify({"error": "nothing to export — run an extraction first"}), 400
    fmt = fmt.lower()
    name = f"timu_export.{fmt}"
    if fmt == "json":
        data, mime = export_json(rep), "application/json"
    elif fmt == "csv":
        data, mime = export_csv(rep), "text/csv"
    elif fmt in ("md", "markdown"):
        data, mime, name = export_markdown(rep), "text/markdown", "timu_export.md"
    elif fmt == "xlsx":
        tmp = HERE / "_timu_export.xlsx"
        export_xlsx(rep, str(tmp))
        return send_file(tmp, as_attachment=True, download_name="timu_export.xlsx")
    else:
        return jsonify({"error": f"unknown format {fmt}"}), 400
    return send_file(io.BytesIO(data.encode("utf-8")), mimetype=mime,
                     as_attachment=True, download_name=name)


def main():
    host = os.environ.get("TIMU_HOST", "127.0.0.1")
    port = int(os.environ.get("TIMU_PORT", "7801"))
    url = f"http://{host}:{port}"
    print(f"\n  TIMU v{TIMU_VERSION}  ->  {url}\n  (Ctrl+C to stop)\n")
    if os.environ.get("TIMU_NO_BROWSER") != "1":
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    app.run(host=host, port=port, threaded=True, debug=False)


if __name__ == "__main__":
    main()
