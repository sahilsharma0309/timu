# TIMU — query-driven web data extraction agent

Give Timu **up to 10 websites** (URLs, or just names like `reactome.org`) and a
**plain-language query** — "saare product names aur price nikalo", "contact email +
phone + address", "all article titles with dates" — and it extracts exactly those
fields from every site, finds the **data they have in common**, and hands you
JSON / CSV / Markdown / XLSX.

Two interfaces, one engine:

| | run it with | what it is |
|---|---|---|
| **Streamlit** | `streamlit run streamlit_app.py` | deploy-anywhere UI, works on Streamlit Community Cloud |
| **Flask + HTML** | `python timu_app.py` | animated dark-neon interface with a live terminal feed |
| **CLI / library** | `python timu_engine.py …` | scriptable, no UI |

```
query  ─▶  intent detection  ─▶  discovery (sitemap / feed / rel=next)
       ─▶  fetch (async HTTP/2, cache+304, or Chromium render)
       ─▶  extraction (15 field extractors)
       ─▶  common-data analysis across sites
       ─▶  JSON · CSV · Markdown · XLSX
```

---

## Quickstart

```bash
git clone https://github.com/sahilsharma0309/timu.git
cd timu
pip install -r requirements.txt

streamlit run streamlit_app.py          # Streamlit UI
# or
python timu_app.py                      # Flask UI on http://127.0.0.1:7801
# or
python timu_engine.py https://site-a.com https://site-b.com -q "emails and prices"

python timu_doctor.py                   # what's installed / what's missing
python test_timu.py                     # 70 offline checks, no network needed
```

JavaScript-rendered sites additionally need a browser, once:

```bash
python -m playwright install chromium
```

Windows users can just double-click `run_timu.bat` (creates a venv, installs, launches).

### Deploy on Streamlit Community Cloud

1. Push this repo to your GitHub (already done if you are reading it there).
2. [share.streamlit.io](https://share.streamlit.io) → **New app** → pick this repo.
3. Branch `main`, main file **`streamlit_app.py`** → **Deploy**.

`requirements.txt` and `packages.txt` are all the config it needs.

Browser render needs two things on a hosted machine, and they fail separately: the
Chromium **binary** (the sidebar's one-time **install chromium** button) and the OS
**shared libraries** it links against. `packages.txt` in this repo carries that library
list — Streamlit Cloud installs it at build time; a bare `playwright install chromium`
without it launches and dies with `libglib-2.0.so.0: cannot open shared object file`.
The sidebar reports both separately (`chromium binary` / `chromium launches`), and a
browser that cannot start degrades the run to HTTP render instead of taking the async
transport down with it.

---

## What a query controls

Timu maps query keywords (English **and** Hinglish) to extractors:

| write this in your query | you get |
|---|---|
| email, mail, contact, sampark | `emails` |
| phone, mobile, number, whatsapp | `phones` |
| price, keemat, daam, rate, fees, mrp | `prices` |
| product, item, listing, job, article, news, review, saman | `items` — repeated cards: name + price + link + image |
| table, rows, columns, stats | `tables` — real rows keyed by header |
| link, url, sitemap | `links` with internal/external flags |
| image, photo, tasveer, logo | `images` with alt text |
| heading, title, topics, menu | `headings` (h1–h4) |
| social, twitter, instagram, linkedin | `social_links` |
| date, tarikh, deadline, published | `dates` |
| address, pata, location, pincode | `addresses` |
| description, about, summary, jankari | `paragraphs` |
| "sara data", "sab kuch", everything, full text | `full_text` |
| schema, json-ld, seo, structured | `structured_data` (schema.org) |

Always included: `meta` (title, description, og:*), `structured_data`, and
`query_matches` — the page lines that contain your query terms.
Need something precise? Put a selector in the query: `css: .product-card h2`.

## Common-data analysis

With 2+ successful sites you also get:

* `shared_fields` — fields present on every site
* `shared_values` — the exact values every site has, per field
* `values_on_multiple_sites` — value → how many sites → which sites
* `overlap_matrix` — per site pair: shared-value count + Jaccard similarity

Matching is normalised: case, whitespace, `https://`, `www.` and trailing `/` are
ignored, so `https://Example.com/` and `example.com` count as the same value.

## Report shape

```
{ query, intents, selector, generated_at, elapsed_s, targets,
  sites: [ {target, url, ok, status, error, pages_fetched, page_urls[],
            data{...}, counts{...},
            fetch:{renderer, from_cache, attempts, discovery{...},
                   api_endpoints[], notes[]}} ],
  summary: {requested, succeeded, failed[], total_records, pages_fetched,
            transport, renderers[], cache_hits, api_endpoints_found, fetch_notes[]},
  common:  {shared_fields, shared_values, values_on_multiple_sites, overlap_matrix} }
```

## Transport (what makes it fast)

| | how |
|---|---|
| Concurrency | asyncio, 16 requests in flight, 2 per host |
| Protocol | HTTP/2 with connection pooling when the server offers it |
| Repeat runs | on-disk cache + `ETag` / `Last-Modified` → **304, zero body** |
| JS pages | Playwright Chromium render, lazy-load scrolling, optional `--wait-for` selector |
| Extra pages | `Sitemap:` from robots.txt, `/sitemap.xml` (incl. nested), RSS/Atom, `rel=next` |
| Rate limits | honours `Retry-After` on 429/503, then exponential backoff |
| API discovery | in browser mode, records the JSON/XHR endpoints the page calls itself |

Politeness is deliberate: 2 concurrent requests per host, 0.5 s spacing, and
robots.txt `Crawl-delay` respected. Not getting banned is the real throughput win.

```python
from timu_engine import TimuScraper, TimuConfig, export_csv

timu = TimuScraper(TimuConfig(max_pages_per_site=3, render="auto", use_cache=True))
rep = timu.run(["site-a.com", "site-b.com"], "emails and phone numbers")

rep["sites"][0]["data"]["emails"]     # per-site data
rep["common"]["shared_values"]        # what both sites share
open("out.csv", "w", encoding="utf-8").write(export_csv(rep))
```

CLI flags: `--render auto|http|browser` · `--wait-for CSS` · `--pages N` · `--no-cache`
· `--no-discover` · `--transport auto|legacy` · `--no-robots` · `--llm-key sk-ant-…`
· `--formats json,csv,md,xlsx`

## Optional AI shaping

Set `ANTHROPIC_API_KEY` (or paste it in the Streamlit sidebar) and Timu additionally
asks a model to shape the page text into query-shaped rows (`llm_rows`). Without a
key, only the deterministic rule-based extractors run — everything else works the same.

---

## When a site refuses the fetch

Blocks are normal, so Timu treats them as a question — *what does this site permit?* — and
answers it instead of failing silently. On a `401/403/405/406/429/451` or a robots.txt
disallow it reads the site's **own published rules**: which robots.txt user-agent group
applies to Timu, its `Allow` / `Disallow` paths, any `Crawl-delay`, and every sitemap the
site advertises, with sample URLs pulled from them. The UI shows this next to the failed
site, with a button to load those sitemap URLs straight into TARGETS.

That distinction matters: a blanket `Disallow: /` means the site does not want automated
access and Timu stops there; a 403 with a permissive robots.txt usually means the refusal
is user-agent or datacenter-IP based (Streamlit Cloud, CI runners), which is why the same
target often works when you run Timu on your own machine. Either way it is read-only
reconnaissance of what the site publishes about itself — no probing of undeclared paths,
and the refused URL is never retried under a different identity.

In the Streamlit sidebar, **🧪 LOAD TEST TARGETS** fills in two sites built for scraping
practice (`books.toscrape.com`, `quotes.toscrape.com`) so you can confirm end-to-end
extraction in one click before pointing Timu at a site that may block it.

## Scope and ethics

Timu is built for **public, permitted data**, and it says who it is: every request
carries a `TimuBot/2.0` User-Agent, robots.txt is honoured by default, `429`s are
obeyed, and there is a per-host delay.

**Not included, by design:** browser-fingerprint or User-Agent spoofing, CAPTCHA or
Cloudflare challenge solving, proxy/IP rotation, cookie or paywall circumvention, or
any "scrape before the block lands" trickery. That is evasion tooling — out of scope
here, and in practice a fast route to ToS termination, IP bans and legal exposure.

**When a site blocks you, the better routes are:** its own JSON API (browser mode's
`FETCH INTEL` panel shows you the endpoints the page itself calls — usually far faster
and cleaner than HTML parsing), an official API or data dump, its sitemap/RSS feed, or
simply requesting access. Timu's discovery features exist to find exactly these.

Also: `robots.txt` can be overridden (`--no-robots`), but that is your call and your
responsibility — keep it to content you are permitted to fetch. And extracting personal
data (emails, phone numbers, addresses) puts you under privacy law (GDPR, India's DPDP
Act); don't use it for spam.

Known limits: login-gated content is out of reach, bot-protected pages will stay
blocked, and `css:` queries need `soupsieve` installed (it's in requirements).

## Testing status

* `python test_timu.py` → **70/70 pass** — extraction (emails, phones, prices, items,
  tables, addresses, dates, JSON-LD, links), Hinglish + English intent detection,
  common-data + Jaccard overlap, all exporters, cache roundtrip, sitemap parsing,
  JS-shell detection, and graceful degradation — all on synthetic fixtures, no network.
* CI runs the doctor + the offline suite on Python 3.11 and 3.12.
* Live run recorded in `examples/`: 4 real sites (reactome, string-db, clinicaltrials,
  ncbi), 2 pages each → 4/4 ok, 330 records, with shared values across sites.
* Live run on three real sites (reactome.org, string-db.org, ncbi.nlm.nih.gov), 3 pages
  each, async HTTP/2 transport: **3/3 sites, 7 pages, 757 records in 24.3 s**; a second
  identical run served 6 pages from cache. Discovery picked real content pages
  (`/what-is-reactome`, `/about/news`) rather than assets. Output is in `examples/`.
* Measured effect of the v2.2 discovery fixes on that same run: 86.3 s → 30.0 s fresh and
  32.1 s → 14.9 s cached (CPU 30 s → 3.3 s), from bounding sitemap work with a time budget
  and a size cap, and from not handing feeds, favicons and CDN infrastructure URLs to the
  HTML extractors.

## Project layout

```
streamlit_app.py    Streamlit UI (deployable)
timu_app.py         Flask server for the animated HTML UI
timu_ui.html        animated interface; opens standalone in DEMO MODE too
timu_engine.py      extraction, intent detection, common-data, exporters, CLI
timu_fetch.py       async HTTP/2 transport, cache, robots, Chromium render, discovery
timu_doctor.py      capability diagnostics
test_timu.py        offline test suite
examples/           a real extraction report in all four formats
```

MIT licensed — see `LICENSE`.
