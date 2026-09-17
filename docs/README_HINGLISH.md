# TIMU v2 — data scraping agent

Ek website ka naam ya URL do (ek saath **max 10**), apni query likho ("saare product
name aur price nikalo"), aur Timu poore page se wahi data nikal ke deta hai — per-site
aur **multiple sites ka common data** bhi. Output JSON / CSV / Markdown / Excel me
download ho jata hai. UI me ek **RESET** button hai jo sab clear kar deta hai.

**v2 me naya:** async HTTP/2 transport (ek saath saari sites + pages), on-disk cache with
304 conditional requests, Playwright browser rendering for JavaScript sites, sitemap /
RSS / `rel=next` discovery, site ke **apne JSON API endpoints** ka detection, presets,
aur ek `FETCH INTEL` tab jo batata hai har site kaise aayi.

```
timu_engine.py     extraction + common-data + export engine  (query -> fields)
timu_fetch.py      transport: async HTTP/2, cache, robots, browser render, discovery
timu_app.py        Flask server: UI + /api/* endpoints
timu_ui.html       animated interface (bina server bhi khulta hai — DEMO MODE)
timu_doctor.py     kya installed hai / kya missing hai — diagnostics
test_timu.py       offline test suite (47 checks, network ki zarurat nahi)
requirements.txt   dependencies
run_timu.bat       Windows: double-click -> venv + install + browser
run_timu.sh        macOS/Linux: bash run_timu.sh
```

---

## 1. Chalane ka tarika

**Windows:** `run_timu.bat` pe double-click. Bas.

**Manually (koi bhi OS):**

```bash
pip install -r requirements.txt
python timu_app.py          # -> http://127.0.0.1:7801  (browser khud khulta hai)
```

Sirf UI dekhna hai? `timu_ui.html` ko browser me kholo — backend na mile to wo
**DEMO MODE** me chalta hai (fake data, saare animations live). Real scraping ke liye
server chahiye.

Port badalna ho: `TIMU_PORT=8000 python timu_app.py`

---

## 2. Interface

| Section | Kya karta hai |
|---|---|
| **TARGETS** | URL ya sirf site ka naam type karo → **Enter** → chip ban jata hai. Comma/space/newline se separate karke 10 URLs ek saath paste bhi kar sakte ho. Har chip pe `×` se hatao. Bare naam (`wikipedia`) pe Timu khud `.com/.org/.in/.io…` probe karta hai. |
| **QUERY** | Apni bhasha me likho — Hinglish bhi chalta hai. Neeche ready-made example pills hain, click karke add ho jate hain. |
| **PAGES/SITE** | 1 = sirf wahi page. 2–8 = utne pages — Timu pehle sitemap/feed/`rel=next` dekhta hai, warna same-host links. |
| **RENDER** | `AUTO` (default) = HTTP se try karo, page JS-shell nikla to browser pe switch. `HTTP` = sabse fast, sirf server HTML. `BROWSER` = har page Playwright Chromium se render (JS sites ke liye). |
| **WAIT FOR** | Browser mode me ek CSS selector — browser usko wait karega phir HTML padhega (`.product-card`, `#results` etc.). |
| **CACHE + 304s** | Fetched pages disk pe cache hote hain; dobara chalane pe ETag/Last-Modified ke saath conditional GET jata hai — unchanged page = 304, zero download. |
| **SITEMAP / FEED / PAGINATION DISCOVERY** | robots.txt ki `Sitemap:` lines, `/sitemap.xml`, RSS/Atom feeds, aur `rel=next` chain se extra pages dhoondta hai. |
| **★ SAVE PRESET** | Targets + query + options browser me save; ek click pe wapas load. |
| **RESPECT ROBOTS.TXT** | Default ON — site ki robots.txt follow hoti hai. |
| **AI SHAPING** | `ANTHROPIC_API_KEY` set ho to LLM page text ko tumhari query ke hisaab se rows me shape karta hai. Key na ho to switch nazar-andaaz ho jata hai. |
| **LIVE FEED** | Terminal-style live log: transport mode, kaunsa site fetch hua, kitne pages, kitne cache se, kya fail hua. |
| **⚡ FETCH INTEL** | Naya tab: har site ka renderer, pages, cache hits, sitemap/feed/pagination counts, aur **site ke apne JSON API endpoints** (browser mode me capture hote hain) — inhe direct hit karna sabse clean raasta hota hai. |
| **EXTRACTED DATA** | Har site ka apna tab + ek **◈ COMMON DATA** tab. Field cards expand/collapse hote hain, aur filter box se results ke andar search hota hai. |
| **⬇ JSON / CSV / MD / XLSX** | Download. XLSX server se aata hai (3 sheets: extraction, common, summary), baaki browser me hi ban jate hain. |
| **⟳ RESET** | Targets, query, logs, results, options — sab clear, animations dubara chalte hain. |

---

## 2.1 Speed aur transport (v2)

| | v1 | v2 |
|---|---|---|
| Sites | thread pool, 5 at a time | asyncio, 16 requests in flight (per-host 2) |
| Protocol | HTTP/1.1 | HTTP/2 jab server de, connection pooling |
| Repeat run | poora download | ETag/Last-Modified → **304, zero body** |
| JS sites | nahi chalta | Playwright Chromium render |
| Extra pages | sirf same-host links | sitemap.xml + feeds + `rel=next` + links |
| Rate limit | kuch nahi | `429`/`503` pe `Retry-After` honour + exponential backoff |

Politeness jaan-boojh kar rakhi gayi hai: per-host 2 parallel requests, 0.5s gap, aur
robots.txt ka `Crawl-delay` follow hota hai. Yeh tumhe *ban hone se bachata* hai — jo
practically sabse badi speed problem hai.

Cache stats dekhne/clear karne ke liye: `GET /api/cache`, `POST /api/cache/clear`.
Cache folder badalna ho: `TIMU_CACHE=path python timu_app.py`.

## 2.2 Sab theek hai ya nahi?

```bash
python timu_doctor.py     # kaunsa package hai, chromium hai ya nahi, cache backend, engine version
python test_timu.py       # 47 offline checks (network ke bina) — extraction, common-data, exports
python timu_fetch.py https://example.com   # live transport test: pages, renderer, discovery
```

## 3. Query kaise likhein

Timu query ke keywords se decide karta hai kaun-kaun se extractor chalane hain
(English **aur** Hinglish dono samajhta hai):

| Query me ye likho | Ye nikalta hai |
|---|---|
| email, mail, contact, sampark | `emails` |
| phone, mobile, number, whatsapp | `phones` |
| price, keemat, daam, rate, fees, mrp | `prices` |
| product, item, listing, job, article, news, review, saman | `items` (repeated cards: name + price + link + image) |
| table, rows, columns, stats | `tables` (real tabular rows, columns ke saath) |
| link, url, sitemap | `links` (internal/external flag ke saath) |
| image, photo, tasveer, logo | `images` (alt text ke saath) |
| heading, title, topics, menu | `headings` (h1–h4) |
| social, twitter, instagram, linkedin | `social_links` |
| date, tarikh, deadline, published | `dates` |
| address, pata, location, pincode | `addresses` |
| description, about, summary, jankari | `paragraphs` |
| "sara data", "sab kuch", everything, full text | `full_text` (poora visible text) |
| schema, json-ld, seo, structured | `structured_data` (schema.org blocks) |

Extra:

* **`meta`** aur **`structured_data`** hamesha nikalte hain (title, description, og:*, schema.org).
* **`query_matches`** — tumhari query ke words jis line me aate hain, wo lines bhi milti hain.
* **CSS selector** chahiye to query me hi likho: `css: .product-card h2` — Timu wahi nodes
  nikal dega (`css_matches`).
* Query khaali chhod do to default set chalta hai: meta + headings + items + links.

---

## 4. Common data (2+ sites)

Jab 2 ya zyada sites successfully scrape hoti hain, `◈ COMMON DATA` tab me:

* **shared_fields** — wo fields jo har site pe mile.
* **shared_values** — exact wahi value jo **sabhi** sites pe hai (field ke hisaab se).
* **values on 2+ sites** — kitni sites pe wo value mili, kaun-kaun si sites.
* **overlap matrix** — har site-pair ke beech shared value count + Jaccard similarity.

Matching normalised hoti hai: case, extra spaces, `https://`, `www.`, trailing `/`
ignore ho jate hain — isliye `https://Example.com/` aur `example.com` same count hote hain.

---

## 5. Python / CLI se

```bash
python timu_engine.py https://site-a.com https://site-b.com \
       -q "all product names and prices" --pages 3 --formats json,csv,md,xlsx -o out

# JS-rendered site, browser se, ek selector ka wait karke:
python timu_engine.py https://spa-site.com -q "products with price" \
       --render browser --wait-for ".product-card" --pages 5

# fast, cache off, sirf HTTP:
python timu_engine.py https://site-a.com -q "emails" --render http --no-cache
```

Flags: `--render auto|http|browser` · `--wait-for CSS` · `--pages N` ·
`--no-cache` · `--no-discover` · `--transport auto|legacy` · `--no-robots` ·
`--llm-key sk-ant-...` · `--formats json,csv,md,xlsx`

```python
from timu_engine import TimuScraper, TimuConfig, export_csv

timu = TimuScraper(TimuConfig(max_pages_per_site=3, render="auto", use_cache=True))
rep = timu.run(["site-a.com", "site-b.com"], "emails and phone numbers")

rep["sites"][0]["data"]["emails"]      # per-site data
rep["common"]["shared_values"]         # dono sites pe common
open("out.csv", "w", encoding="utf-8").write(export_csv(rep))
```

`run()` ka report structure:

```
{ query, intents, selector, generated_at, elapsed_s, targets,
  sites: [ {target, url, ok, status, error, pages_fetched, data{...}, counts{...},
            fetch:{renderer, from_cache, attempts, discovery{...}, api_endpoints[], notes[]}} ],
  summary: {requested, succeeded, failed[], total_records, pages_fetched,
            transport, renderers[], cache_hits, api_endpoints_found, fetch_notes[]},
  common:  {shared_fields, shared_values, values_on_multiple_sites, overlap_matrix} }
```

---

Sirf transport chahiye (extraction ke bina)?

```python
import timu_fetch as tf

out = tf.run_sync(tf.fetch_sites(
    ["https://a.test/", "https://b.test/"], pages=5, render="auto",
    cfg=tf.FetchConfig(total_concurrency=16, per_host_concurrency=2, use_cache=True)))

for site in out:
    ok = [r for r in site["all_results"] if r.ok]
    print(site["url"], len(ok), ok[0].renderer, site["discovery"]["counts"])
    print(site["api_endpoints"])        # site ke apne JSON endpoints (browser mode)
```

## 6. Kya kaam nahi karega — aur kyun

**v2 me theek ho gaya:**

* **JavaScript-rendered sites** — `RENDER = BROWSER` (ya `AUTO`, jo khud detect karta hai)
  Playwright Chromium se page render karta hai, scroll karke lazy content load karta hai,
  phir HTML padhta hai. Iske liye ek baar `python -m playwright install chromium` chahiye.
* **Bade sites se thoda-thoda data** — sitemap/feed/pagination discovery se hazaaron URLs
  mil jate hain; `--pages` badha do.
* **Rate limiting** — `429`/`503` pe server ka `Retry-After` follow hota hai, blind retry nahi.

**Jo Timu jaan-boojh kar nahi karta (aur main isme change nahi karunga):**

Timu me **koi anti-detection / evasion layer nahi hai** — na browser fingerprint ya
User-Agent spoofing, na CAPTCHA ya Cloudflare challenge solving, na proxy/IP rotation,
na cookie/paywall bypass, na "block hone se pehle scrape kar lo taaki pata na chale"
wala behaviour. Timu har request pe khud ko `TimuBot/2.0` bata kar jata hai, robots.txt
default me follow karta hai, `429` pe ruk jata hai, aur jahan site mana kar de wahan ruk
jata hai. Uska maqsad site ka access control chakma dena hota hai — woh evasion tooling
hai, aur iske raaste practically bhi ToS termination, IP ban, aur legal notice pe khatam
hote hain. Ye scope se bahar hai.

**Jab koi site block kare, asli (aur behtar) raaste ye hain:**

1. **Site ka apna API use karo.** `RENDER = BROWSER` pe `FETCH INTEL` tab me Timu tumhe
   wahi JSON/XHR endpoints dikha deta hai jo page khud call karta hai — wo clean JSON
   deta hai, HTML parse se 10-100x fast hai, aur pagination bhi saaf hoti hai.
2. **Official API / data dump / sitemap** — bohot si sites ke paas public API, CSV dump,
   ya `/sitemap.xml` hota hai. Timu discovery wahi dhoondta hai.
3. **Access maang lo** — API key, partner feed, ya research access. Bulk data ke liye
   ye sabse sasta raasta hai.
4. **RSS/Atom feeds** — news/blog data ke liye banaya hi gaya hai; Timu inhe detect karta hai.

**Ab bhi limitations:**

* **Login ke peeche ka data** — Timu login nahi karta.
* **Bot protection** (Cloudflare challenge, "Client Challenge" pages) — block hoga, aur
  Timu usse bypass karne ki koshish nahi karega.
* **robots.txt disallow** — default me fetch nahi karega. `--no-robots` / UI switch se tum
  override kar sakte ho; wo tumhari zimmedari hai, aur public/ToS-allowed content tak
  hi seemit rakho.
* **Personal data** (emails/phones/addresses) — extract karna aasan hai, par uska use
  privacy laws (GDPR / DPDP Act) ke under aata hai. Marketing spam ke liye mat use karo.
* **Sandbox me sirf allowlisted domains** reachable hote hain — apne laptop pe koi limit nahi.

---

## 7. Testing status (honest)

* **`python test_timu.py` → 47/47 pass.** Ye extraction (emails / phones / prices /
  items / tables / addresses / dates / JSON-LD / links), intent detection (Hinglish +
  English), common-data + Jaccard overlap, teeno exporters, cache roundtrip, sitemap
  parsing, JS-shell detection, aur graceful degradation — sab synthetic HTML fixtures
  pe check karta hai, network ke bina.
* **v1 ka live run:** 4 real sites (reactome, string-db, clinicaltrials, ncbi), 2 pages
  per site → **4/4 ok, 330 records**, common tab me `Download` (3 sites) aur
  `Help`/`Funding`/`Partners`/`Statistics` (2 sites). Output `timu_demo_report.*` me hai.
* **v2 ka live network path (async HTTP/2, browser render, discovery) is build machine
  pe benchmark nahi ho paya** — host ki Application Control policy ne beech me
  `unicodedata` / `_sqlite3` DLLs block kar diye, jisse `httpx`, `requests`, `flask` aur
  Chromium launch sab is sandbox me import/chal nahi paye. Code logically test hua hai
  (offline suite + syntax + graceful fallbacks), par asli speed number tumhare laptop pe
  hi banega. Pehla command yahi chalao:

  ```bash
  python timu_doctor.py
  python timu_fetch.py https://your-site.com
  ```

  Agar `httpx` missing ho to Timu chup-chaap legacy sequential fetcher pe chala jata hai
  (UI ke LIVE FEED me `transport: legacy-requests` dikh jayega), aur Playwright na ho to
  browser mode HTTP pe fallback ho jata hai — crash nahi hota.
* Ek known chhoti baat: `css:` selector queries ke liye `soupsieve` install hona chahiye
  (requirements me hai). Na ho to Timu us field pe saaf error deta hai, baaki sab chalta hai.
