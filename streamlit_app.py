"""
Timu — Streamlit interface
==========================

    pip install -r requirements.txt
    streamlit run streamlit_app.py

Deploy on Streamlit Community Cloud: New app -> pick this repo -> branch `main`
-> main file `streamlit_app.py`. Nothing else to configure; Timu falls back
gracefully when an optional piece (Playwright/Chromium) is missing on the host.

The engine is shared with the Flask UI: timu_engine.py does extraction and
common-data analysis, timu_fetch.py does the async HTTP/2 + browser transport.
"""

from __future__ import annotations

import io
import json
import os
import sys
import time
from datetime import datetime, timezone

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import timu_engine as te                                            # noqa: E402

try:
    import timu_fetch as tf
except Exception:                                                   # pragma: no cover
    tf = None                                                       # type: ignore

MAX = te.MAX_TARGETS
EXAMPLES = [
    "saare product names aur price nikalo",
    "contact email + phone number + address",
    "all headings and internal links",
    "latest article titles with dates",
    "sabhi tables ka data",
    "pricing plans and features",
    "job listings with company name",
    "css: .product-card h2",
]

st.set_page_config(page_title="TIMU — data extraction agent", page_icon="⚡",
                   layout="wide", initial_sidebar_state="expanded")

# --------------------------------------------------------------- styling ----
st.markdown("""
<style>
:root{--cyan:#22e6ff;--mint:#39ffb0;--violet:#a97bff;--pink:#ff4d9d;--amber:#ffc447;}
html, body, [class*="css"], .stMarkdown, .stTextInput, .stTextArea{
  font-family:"SFMono-Regular",Consolas,"Roboto Mono",monospace;}
.stApp{background:
  radial-gradient(1100px 600px at 10% -10%,#0d2134 0%,transparent 60%),
  radial-gradient(900px 500px at 105% 10%,#1a0f2e 0%,transparent 55%), #04070d;}
section[data-testid="stSidebar"]{background:rgba(7,12,22,.92);
  border-right:1px solid rgba(34,230,255,.22);}
h1,h2,h3{letter-spacing:2px}
.stButton>button{font-family:inherit;font-weight:700;letter-spacing:2px;border-radius:12px;
  border:1px solid rgba(34,230,255,.35);background:rgba(34,230,255,.08);color:#d7e6f5;
  transition:.2s;}
.stButton>button:hover{transform:translateY(-2px);border-color:var(--cyan);
  background:rgba(34,230,255,.18);box-shadow:0 8px 26px rgba(34,230,255,.25);}
.stDownloadButton>button{border-radius:12px;font-weight:700;letter-spacing:1.5px;
  background:linear-gradient(95deg,#22e6ff,#39ffb0);color:#03131a;border:none;}
div[data-testid="stMetric"]{border:1px solid rgba(34,230,255,.22);border-radius:14px;
  padding:12px 14px;background:rgba(34,230,255,.045);}
div[data-testid="stMetricValue"]{color:var(--mint);text-shadow:0 0 16px rgba(57,255,176,.4);}
.stTabs [data-baseweb="tab"]{font-size:12px;letter-spacing:1.5px;}
.stTabs [aria-selected="true"]{color:#03131a!important;
  background:linear-gradient(95deg,#22e6ff,#39ffb0);border-radius:9px 9px 0 0;}
textarea, .stTextInput input{background:rgba(4,10,20,.85)!important;color:#d7e6f5!important;
  border:1px solid rgba(34,230,255,.22)!important;font-family:inherit!important;}
.timu-chip{display:inline-block;padding:5px 10px;margin:3px 4px 0 0;border-radius:9px;
  border:1px solid rgba(57,255,176,.35);background:rgba(57,255,176,.08);color:#c9ffe9;
  font-size:11.5px;}
.timu-chip.bad{border-color:rgba(255,77,157,.45);background:rgba(255,77,157,.08);color:#ffd5e6;}
.timu-log{background:rgba(2,6,12,.75);border:1px solid rgba(34,230,255,.14);border-radius:12px;
  padding:12px 14px;font-size:11.5px;line-height:1.7;max-height:260px;overflow:auto;
  white-space:pre-wrap;color:#9fd8e8;}
.timu-note{border:1px solid rgba(255,196,71,.35);background:rgba(255,196,71,.07);
  border-radius:12px;padding:10px 13px;font-size:12px;color:#ffe6b0;}
</style>
""", unsafe_allow_html=True)

LOGO_TPL = """
<style>
.tl-wrap{display:grid;place-items:center}
.tl svg{overflow:visible}
.tl g{transform-box:fill-box;transform-origin:center}
.tl .outer{animation:tlspin 9s linear infinite}
.tl .mid{animation:tlspin 6s linear infinite reverse}
.tl .core{animation:tlcore 3.2s ease-in-out infinite}
.tl .halo{animation:tlhalo 3.2s ease-in-out infinite}
.tl.busy .outer{animation-duration:1.5s}
.tl.busy .mid{animation-duration:1s}
.tl.busy .core{animation-duration:.8s}
@keyframes tlspin{to{transform:rotate(360deg)}}
@keyframes tlcore{0%,100%{transform:rotate(0deg) scale(1)}50%{transform:rotate(180deg) scale(1.18)}}
@keyframes tlhalo{0%,100%{opacity:.25;transform:scale(1)}50%{opacity:.6;transform:scale(1.1)}}
</style>
<div class="tl-wrap"><div class="tl {cls}">
<svg viewBox="0 0 120 120" width="{size}" height="{size}" fill="none">
  <defs>
    <filter id="tlglow{uid}" x="-60%" y="-60%" width="220%" height="220%">
      <feGaussianBlur stdDeviation="3.2" result="b"/>
      <feMerge><feMergeNode in="b"/><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <linearGradient id="tlo{uid}" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#7fe9ff"/><stop offset="1" stop-color="#22e6ff"/>
    </linearGradient>
  </defs>
  <g class="halo"><rect x="10" y="10" width="100" height="100" rx="30"
        fill="rgba(34,230,255,.10)" stroke="rgba(34,230,255,.35)" stroke-width="2"/></g>
  <g filter="url(#tlglow{uid})">
    <g class="outer"><rect x="16" y="16" width="88" height="88" rx="26"
          fill="rgba(10,30,45,.55)" stroke="url(#tlo{uid})" stroke-width="4"
          stroke-linejoin="round"/></g>
    <g class="mid"><rect x="35" y="35" width="50" height="50" rx="17"
          stroke="#ff4d9d" stroke-width="4" stroke-linejoin="round"/></g>
    <g class="core"><rect x="48" y="48" width="24" height="24" rx="9"
          fill="rgba(57,255,176,.22)" stroke="#39ffb0" stroke-width="3.5"
          stroke-linejoin="round"/></g>
  </g>
</svg></div></div>
"""


def logo(size: int = 92, busy: bool = False, uid: str = "a") -> str:
    """The Timu mark: three nested rounded squares, counter-rotating."""
    return LOGO_TPL.replace("{size}", str(size)).replace(
        "{cls}", "busy" if busy else "").replace("{uid}", uid)


HEADER = """
<div style="position:relative;height:150px;border-radius:16px;overflow:hidden;
     border:1px solid rgba(34,230,255,.22);background:#05080f">
<canvas id="c" style="position:absolute;inset:0"></canvas>
<div style="position:absolute;inset:0;display:flex;align-items:center;
     gap:22px;padding:0 26px;font-family:Consolas,monospace">
  __LOGO__
  <div>
  <div style="font-size:42px;font-weight:800;letter-spacing:12px;
       background:linear-gradient(92deg,#22e6ff,#39ffb0 40%,#a97bff 75%,#ff4d9d);
       -webkit-background-clip:text;background-clip:text;color:transparent">TIMU</div>
  <div style="font-size:11px;letter-spacing:3px;color:#6f8399;margin-top:6px">
     QUERY → DISCOVER → RENDER → EXTRACT → COMPARE → DOWNLOAD</div>
  </div>
</div></div>
<script>
const cv=document.getElementById('c'),x=cv.getContext('2d');let w,h,P=[];
function rs(){w=cv.width=cv.offsetWidth;h=cv.height=cv.offsetHeight;P=[];
  for(let i=0;i<Math.min(70,Math.floor(w*h/9000));i++)
    P.push({x:Math.random()*w,y:Math.random()*h,vx:(Math.random()-.5)*.45,
            vy:(Math.random()-.5)*.45,r:Math.random()*1.6+.5});}
rs();addEventListener('resize',rs);
(function loop(){x.clearRect(0,0,w,h);
  for(const p of P){p.x+=p.vx;p.y+=p.vy;
    if(p.x<0||p.x>w)p.vx*=-1;if(p.y<0||p.y>h)p.vy*=-1;
    x.beginPath();x.arc(p.x,p.y,p.r,0,7);x.fillStyle='rgba(34,230,255,.8)';x.fill();}
  for(let i=0;i<P.length;i++)for(let j=i+1;j<P.length;j++){
    const a=P[i],b=P[j],d=Math.hypot(a.x-b.x,a.y-b.y);
    if(d<110){x.strokeStyle='rgba(57,255,176,'+(.18*(1-d/110))+')';x.lineWidth=.8;
      x.beginPath();x.moveTo(a.x,a.y);x.lineTo(b.x,b.y);x.stroke();}}
  requestAnimationFrame(loop);})();
</script>
"""

# ----------------------------------------------------------------- state ----
DEFAULTS = {"targets_raw": "", "query": "", "report": None, "logs": [], "running": False,
            "pages": 1, "render": "auto", "wait_for": "", "robots": True, "cache": True,
            "discover": True, "api_key": "", "filter": ""}
for k, v in DEFAULTS.items():
    st.session_state.setdefault(k, v)


def reset_all():
    for k, v in DEFAULTS.items():
        st.session_state[k] = v


def parse_targets(raw: str) -> tuple[list[str], list[str]]:
    seen, good, dropped = set(), [], []
    for tok in str(raw or "").replace(",", "\n").replace(";", "\n").split():
        t = tok.strip().strip('"\'')
        if not t or t.lower() in seen:
            continue
        if not te.normalise_target(t):
            dropped.append(t)
            continue
        seen.add(t.lower())
        if len(good) >= MAX:
            dropped.append(t)
            continue
        good.append(t)
    return good, dropped


def kind_of(t: str) -> str:
    if t.startswith(("http://", "https://")):
        return "URL"
    return "DOMAIN" if "." in t else "NAME→probe"


# --------------------------------------------------------------- sidebar ----
with st.sidebar:
    components.html(logo(74, uid="side"), height=96)
    st.markdown("### ⚙ CONFIG")
    st.session_state.pages = st.slider("Pages per site", 1, 8, st.session_state.pages,
                                       help="1 = sirf wahi page. >1 pe Timu sitemap / feed / "
                                            "rel=next se extra pages dhoondta hai.")
    st.session_state.render = st.radio(
        "Render mode", ["auto", "http", "browser"],
        index=["auto", "http", "browser"].index(st.session_state.render), horizontal=True,
        help="auto = HTTP se try karo, JS-shell mile to browser. http = sabse fast. "
             "browser = Playwright Chromium (JS sites).")
    if st.session_state.render == "browser":
        if tf:
            _ok, _why = tf.browser_probe()
            if not _ok:
                st.warning(f"browser render available nahi hai — {_why}. Timu HTTP render pe "
                           f"chala lega (crash nahi hoga).")
        st.session_state.wait_for = st.text_input("Wait for CSS selector",
                                                  st.session_state.wait_for,
                                                  placeholder=".product-card")
    st.session_state.robots = st.toggle("Respect robots.txt", st.session_state.robots)
    st.session_state.cache = st.toggle("Cache + 304 conditional GETs", st.session_state.cache)
    st.session_state.discover = st.toggle("Sitemap / feed / pagination discovery",
                                          st.session_state.discover)
    with st.expander("AI shaping (optional)"):
        st.session_state.api_key = st.text_input(
            "ANTHROPIC_API_KEY", st.session_state.api_key, type="password",
            help="Key do to LLM page text ko tumhari query ke hisaab se rows me shape karega. "
                 "Khaali chhodo to sirf rule-based extractors chalenge.")
    st.divider()
    if st.button("🧪  LOAD TEST TARGETS", use_container_width=True,
                 help="Do sites jo scraping practice ke liye hi banayi gayi hain — "
                      "inse tum turant dekh sakte ho ki extraction poora kaam karta hai."):
        st.session_state.targets_raw = ("https://books.toscrape.com/\n"
                                        "https://quotes.toscrape.com/")
        st.session_state.query = ("saare product names aur price nikalo, headings aur "
                                  "internal links bhi")
        st.session_state.pages = 3
        st.session_state.report = None
        st.rerun()
    if st.button("⟳  RESET EVERYTHING", use_container_width=True):
        reset_all()
        st.rerun()

    with st.expander("🩺 host capabilities"):
        rows = [("engine", f"v{te.TIMU_VERSION}"),
                ("extractors", str(len(te.EXTRACTORS))),
                ("async HTTP/2 (httpx)", "yes" if (tf and tf.HAVE_HTTPX) else "no"),
                ("playwright", "yes" if (tf and tf.HAVE_PLAYWRIGHT) else "no")]
        if tf:
            ok, info = tf.chromium_available()
            rows.append(("chromium binary", "yes" if ok else "no"))
            if ok:
                lok, linfo = tf.browser_probe()
                rows.append(("chromium launches", "yes" if lok else "NO"))
                if not lok:
                    st.session_state["_browser_why"] = linfo
            try:
                c = tf.PageCache(os.environ.get("TIMU_CACHE", ".timu_cache"))
                rows.append(("cache", f"{c.backend}, {c.stats()['pages']} pages"))
            except Exception as e:
                rows.append(("cache", f"unavailable ({e.__class__.__name__})"))
        st.dataframe(pd.DataFrame(rows, columns=["capability", "status"]),
                     hide_index=True, use_container_width=True)
        why = st.session_state.get("_browser_why")
        if why:
            st.markdown(f'<div class="timu-note">browser render nahi chalega: {why}</div>',
                        unsafe_allow_html=True)
            st.caption("Streamlit Cloud pe repo ke `packages.txt` me system libraries hain — "
                       "usse deploy karo, phir app reboot pe browser mode chal jayega.")
        if tf and tf.HAVE_PLAYWRIGHT and not tf.chromium_available()[0]:
            st.caption("Browser render ke liye Chromium chahiye.")
            if st.button("⬇ install chromium (one-time)", use_container_width=True):
                import subprocess
                with st.spinner("playwright install chromium…"):
                    p = subprocess.run([sys.executable, "-m", "playwright", "install",
                                        "chromium"], capture_output=True, text=True)
                (st.success if p.returncode == 0 else st.error)(
                    (p.stdout or p.stderr or "")[-800:] or f"exit {p.returncode}")
        if tf:
            if st.button("🗑 clear page cache", use_container_width=True):
                try:
                    tf.PageCache(os.environ.get("TIMU_CACHE", ".timu_cache")).clear()
                    st.success("cache cleared")
                except Exception as e:
                    st.error(f"{e.__class__.__name__}: {e}")

    st.caption("Timu identifies itself as TimuBot and honours robots.txt. No stealth, no "
               "CAPTCHA bypass, no proxy rotation — blocked site ka raasta uska API/sitemap "
               "hai (FETCH INTEL tab dekho).")

# ---------------------------------------------------------------- header ----
components.html(HEADER.replace("__LOGO__", logo(96, uid="hdr")), height=162)

# ---------------------------------------------------------------- inputs ----
c1, c2 = st.columns([1, 1], gap="large")
with c1:
    st.markdown("#### ◈ TARGETS")
    st.session_state.targets_raw = st.text_area(
        "URLs ya site ke naam — ek per line (max 10)", st.session_state.targets_raw,
        height=132, label_visibility="collapsed",
        placeholder="https://example.com/products\nflipkart\nreactome.org")
    targets, dropped = parse_targets(st.session_state.targets_raw)
    if targets:
        st.markdown("".join(
            f'<span class="timu-chip">{i+1:02d} · {t[:46]} · {kind_of(t)}</span>'
            for i, t in enumerate(targets)), unsafe_allow_html=True)
    if dropped:
        st.markdown("".join(f'<span class="timu-chip bad">dropped: {d[:40]}</span>'
                            for d in dropped[:6]), unsafe_allow_html=True)
        st.caption(f"{len(dropped)} target(s) dropped — limit {MAX} hai, ya value parse nahi hui.")

with c2:
    st.markdown("#### ◈ QUERY")
    st.session_state.query = st.text_area(
        "Kya nikalna hai (Hinglish chalta hai)", st.session_state.query, height=132,
        label_visibility="collapsed",
        placeholder="saare product names aur price nikalo\n"
                    "contact email, phone number aur address chahiye\n"
                    "css: .product-card h2")
    ex_cols = st.columns(4)
    for i, ex in enumerate(EXAMPLES):
        if ex_cols[i % 4].button(ex[:22] + ("…" if len(ex) > 22 else ""), key=f"ex{i}",
                                 use_container_width=True):
            st.session_state.query = (st.session_state.query.strip() + "\n" + ex).strip()
            st.rerun()

if st.session_state.query:
    st.caption("fields → " + ", ".join(te.detect_intents(st.session_state.query)))

run_col, _ = st.columns([1, 3])
go = run_col.button("⚡  EXTRACT DATA", type="primary", use_container_width=True,
                    disabled=not targets)

# ------------------------------------------------------------------- run ----
if go and targets:
    st.session_state.logs = []
    spin_col, log_col = st.columns([1, 9])
    with spin_col:
        components.html(logo(66, busy=True, uid="run"), height=88)
    log_box = log_col.empty()
    prog = st.progress(0.0, text="booting Timu…")
    done = {"n": 0}
    total = max(1, len(targets))

    def stamp() -> str:
        return datetime.now().strftime("%H:%M:%S")

    def say(e: dict):
        ev = e.get("event")
        L = st.session_state.logs
        if ev == "run_start":
            L.append(f"[{stamp()}] fields → {', '.join(e.get('intents') or [])}")
            if e.get("selector"):
                L.append(f"[{stamp()}] css selector → {e['selector']}")
        elif ev == "transport":
            L.append(f"[{stamp()}] transport: {e.get('mode')} · render={e.get('render')} "
                     f"· cache={'on' if e.get('cache') else 'off'}")
        elif ev == "warn":
            L.append(f"[{stamp()}] ⚠ {e.get('message')}")
        elif ev == "site_start":
            L.append(f"[{stamp()}] ⇢ fetching {e.get('target')}")
        elif ev == "fetch_done":
            L.append(f"[{stamp()}] ⤓ {e.get('target')} → {e.get('pages')} page(s) via "
                     f"{e.get('renderer')}"
                     + (f" ({e.get('cached')} from cache)" if e.get("cached") else ""))
            for n in e.get("notes") or []:
                L.append(f"[{stamp()}]   ↳ {n}")
        elif ev == "site_done":
            done["n"] += 1
            if e.get("ok"):
                n = sum((e.get("counts") or {}).values())
                L.append(f"[{stamp()}] ✓ {e.get('target')} → {n} records")
            else:
                L.append(f"[{stamp()}] ✕ {e.get('target')} → {e.get('error')}")
            prog.progress(min(0.98, 0.1 + 0.88 * done["n"] / total),
                          text=f"{done['n']}/{total} sites done")
        elif ev == "run_done":
            prog.progress(1.0, text="complete")
        log_box.markdown(f'<div class="timu-log">{"<br>".join(L[-200:])}</div>',
                         unsafe_allow_html=True)

    cfg = te.TimuConfig(
        max_pages_per_site=int(st.session_state.pages),
        respect_robots=bool(st.session_state.robots),
        render=st.session_state.render,
        wait_for=(st.session_state.wait_for or None) if st.session_state.render == "browser"
        else None,
        use_cache=bool(st.session_state.cache),
        discover=bool(st.session_state.discover),
        cache_path=os.environ.get("TIMU_CACHE", ".timu_cache"),
        concurrency=min(5, max(1, len(targets))))
    key = st.session_state.api_key or os.environ.get("ANTHROPIC_API_KEY") or ""
    llm = te.anthropic_llm(key) if key else None

    t0 = time.time()
    try:
        st.session_state.report = te.TimuScraper(cfg=cfg, llm_fn=llm).run(
            targets, st.session_state.query, progress=say)
    except Exception as e:                                          # noqa: BLE001
        st.session_state.report = None
        st.error(f"extraction failed — {e.__class__.__name__}: {e}")
    prog.empty()
    st.caption(f"finished in {time.time() - t0:.2f}s")

# --------------------------------------------------------------- results ----
R = st.session_state.report


def field_frame(name: str, value) -> pd.DataFrame | None:
    if isinstance(value, list) and value and isinstance(value[0], dict):
        return pd.DataFrame(value)
    if isinstance(value, list):
        return pd.DataFrame({name: [str(v) for v in value]})
    if isinstance(value, dict):
        return pd.DataFrame({"key": list(value.keys()),
                             "value": [str(v) for v in value.values()]})
    return None


def show_advice(site: dict, key: str):
    """A site refused us — show what it does permit (robots rules + its sitemaps)."""
    adv = ((site.get("fetch") or {}).get("advice")) or {}
    if not adv:
        return
    if adv.get("verdict"):
        st.markdown(f'<div class="timu-note">{adv["verdict"]}</div>', unsafe_allow_html=True)
    st.dataframe(pd.DataFrame([
        {"field": "robots.txt", "value": adv.get("robots_url", "")},
        {"field": "robots available", "value": "yes" if adv.get("robots_available") else "no"},
        {"field": "rules apply to", "value": adv.get("applies_to") or "—"},
        {"field": "crawl-delay", "value": adv.get("crawl_delay") or "—"},
        {"field": "Allow", "value": ", ".join(adv.get("allow") or []) or "—"},
        {"field": "Disallow", "value": ", ".join((adv.get("disallow") or [])[:12]) or "—"},
    ]), hide_index=True, use_container_width=True)
    if adv.get("sitemaps"):
        st.caption("sitemaps the site advertises")
        st.dataframe(pd.DataFrame([{k: (", ".join(v[:2]) if isinstance(v, list) else v)
                                    for k, v in sm.items()} for sm in adv["sitemaps"]]),
                     hide_index=True, use_container_width=True)
    samples = adv.get("sample_urls") or []
    if samples:
        st.caption(f"{len(samples)} URL(s) jo site khud sitemap me publish karti hai — "
                   f"inhe target bana kar dubara try karo")
        st.dataframe(pd.DataFrame({"url": samples}), hide_index=True, use_container_width=True)
        if st.button("➜ in URLs ko TARGETS me daal do", key=f"adv_{key}",
                     use_container_width=False):
            st.session_state.targets_raw = "\n".join(samples[:MAX])
            st.session_state.report = None
            st.rerun()


def show_field(name: str, value, filt: str):
    n = len(value) if isinstance(value, (list, dict)) else 1
    with st.expander(f"{name}  ·  {n}", expanded=(name in ("items", "meta", "tables"))):
        if name == "tables" and isinstance(value, list):
            for t in value:
                st.caption(t.get("caption") or f"table {t.get('index')}")
                rows = t.get("rows") or []
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            return
        df = field_frame(name, value)
        if df is None:
            st.text(str(value)[:20000])
            return
        if filt:
            mask = df.apply(lambda r: filt.lower() in " ".join(map(str, r.values)).lower(),
                            axis=1)
            df = df[mask]
        st.dataframe(df, use_container_width=True, hide_index=True)


if R:
    su = R.get("summary", {})
    common = R.get("common", {}) or {}
    shared = sum(len(v) for v in (common.get("shared_values") or {}).values())

    st.markdown("### ◈ EXTRACTED DATA")
    m = st.columns(6)
    m[0].metric("SITES OK", f"{su.get('succeeded', 0)}/{su.get('requested', 0)}")
    m[1].metric("PAGES", su.get("pages_fetched", "—"))
    m[2].metric("RECORDS", su.get("total_records", 0))
    m[3].metric("COMMON VALUES", shared or len(common.get("values_on_multiple_sites") or []))
    m[4].metric("CACHE HITS", su.get("cache_hits", 0))
    m[5].metric("SECONDS", R.get("elapsed_s", 0))

    base = "timu_" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    d1, d2, d3, d4 = st.columns(4)
    d1.download_button("⬇ JSON", te.export_json(R), f"{base}.json", "application/json",
                       use_container_width=True)
    d2.download_button("⬇ CSV", te.export_csv(R), f"{base}.csv", "text/csv",
                       use_container_width=True)
    d3.download_button("⬇ MARKDOWN", te.export_markdown(R), f"{base}.md", "text/markdown",
                       use_container_width=True)
    try:
        buf = io.BytesIO()
        tmp = os.path.join(os.environ.get("TMPDIR", "."), f"{base}.xlsx")
        te.export_xlsx(R, tmp)
        with open(tmp, "rb") as fh:
            buf.write(fh.read())
        os.remove(tmp)
        d4.download_button("⬇ XLSX", buf.getvalue(), f"{base}.xlsx",
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           use_container_width=True)
    except Exception as e:                                          # noqa: BLE001
        d4.caption(f"XLSX unavailable ({e.__class__.__name__})")

    st.session_state.filter = st.text_input("filter inside results",
                                            st.session_state.filter,
                                            placeholder="type to filter rows…")
    filt = st.session_state.filter.strip()

    names = ["◈ COMMON", "⚡ FETCH INTEL"] + [
        ("● " if (s or {}).get("ok") else "✕ ") + (s or {}).get("target", "?")
        for s in R.get("sites", [])]
    tabs = st.tabs(names)

    # ---- common ----
    with tabs[0]:
        if not common.get("shared_values") and not common.get("values_on_multiple_sites"):
            st.info(common.get("note") or "Sites ke beech koi identical value nahi mili. "
                                          "2+ sites successfully scrape honi chahiye.")
        else:
            st.caption("comparing: " + "  ·  ".join(common.get("sites_compared") or []))
            ov = common.get("overlap_matrix") or {}
            if ov:
                st.dataframe(pd.DataFrame(
                    [{"pair": k, "shared values": v.get("shared"), "jaccard": v.get("jaccard")}
                     for k, v in ov.items()]), hide_index=True, use_container_width=True)
            for f, rows in (common.get("shared_values") or {}).items():
                with st.expander(f"shared · {f}  ·  {len(rows)}", expanded=True):
                    st.dataframe(pd.DataFrame([{"value": str(r["value"])} for r in rows]),
                                 hide_index=True, use_container_width=True)
            multi = common.get("values_on_multiple_sites") or []
            if multi:
                with st.expander(f"values on 2+ sites  ·  {len(multi)}", expanded=False):
                    st.dataframe(pd.DataFrame(
                        [{"value": str(r["value"]), "sites": r["site_count"],
                          "where": ", ".join(r.get("sites") or [])} for r in multi]),
                        hide_index=True, use_container_width=True)

    # ---- fetch intel ----
    with tabs[1]:
        st.caption(f"transport {su.get('transport', '?')} · renderers "
                   f"{', '.join(su.get('renderers') or []) or '?'} · "
                   f"{su.get('pages_fetched', 0)} pages · {su.get('cache_hits', 0)} from cache "
                   f"· {su.get('api_endpoints_found', 0)} JSON endpoint(s) spotted")
        for n in su.get("fetch_notes") or []:
            st.markdown(f'<div class="timu-note">{n}</div>', unsafe_allow_html=True)
        for s in R.get("sites", []):
            if not s:
                continue
            f = s.get("fetch") or {}
            disc = f.get("discovery") or {}
            with st.expander(f"⇢ {s.get('target')}  ·  {s.get('pages_fetched', 0)} page(s)",
                             expanded=True):
                st.dataframe(pd.DataFrame([
                    {"field": "renderer", "value": f.get("renderer", "?")},
                    {"field": "status", "value": (f"HTTP {s.get('status')}" if s.get("ok")
                                                  else f"FAILED — {s.get('error')}")},
                    {"field": "from cache", "value": f.get("from_cache", 0)},
                    {"field": "attempts", "value": f.get("attempts", 1)},
                    {"field": "discovery", "value": json.dumps(disc.get("counts") or {})},
                ]), hide_index=True, use_container_width=True)
                eps = f.get("api_endpoints") or []
                if eps:
                    st.markdown('<div class="timu-note">Ye site khud JSON endpoints call karti '
                                'hai — inhe direct hit karna sabse clean + fast raasta hai.</div>',
                                unsafe_allow_html=True)
                    st.dataframe(pd.DataFrame(eps), hide_index=True, use_container_width=True)
                for key_, label in (("sitemaps", "sitemaps"), ("feeds", "feeds"),
                                    ("pagination", "pagination")):
                    v = disc.get(key_)
                    if v:
                        st.caption(label)
                        st.dataframe(pd.DataFrame(v if isinstance(v[0], dict)
                                                  else [{"url": u} for u in v]),
                                     hide_index=True, use_container_width=True)
                for n in f.get("notes") or []:
                    st.markdown(f'<div class="timu-note">{n}</div>', unsafe_allow_html=True)
                if not s.get("ok"):
                    show_advice(s, f"intel_{s.get('target')}")

    # ---- per site ----
    for tab, s in zip(tabs[2:], R.get("sites", [])):
        with tab:
            if not s:
                st.warning("no data")
                continue
            if not s.get("ok"):
                st.error(f"{s.get('target')} — HTTP {s.get('status') or '—'} · "
                         f"{s.get('error') or 'fetch failed'}")
                show_advice(s, f"site_{s.get('target')}")
                st.caption("Aur try karne layak: poora https:// URL · spelling · site "
                           "JS-rendered ho to RENDER = browser · apne network se chalao "
                           "(datacenter IP blocks bahut common hain).")
                continue
            st.caption(f"{s.get('url')}  ·  HTTP {s.get('status')}  ·  "
                       f"{s.get('pages_fetched')} page(s)  ·  {s.get('elapsed_ms')}ms")
            data = s.get("data") or {}
            if not data:
                st.info("page fetched but nothing matched the query")
            for name, value in data.items():
                show_field(name, value, filt)

    with st.expander("raw report (JSON)"):
        st.json(R, expanded=False)
else:
    st.info("Targets aur query daal ke **EXTRACT DATA** dabao. Ek saath 10 sites tak, "
            "aur 2+ sites pe COMMON tab me unka shared data bhi mil jayega.")
