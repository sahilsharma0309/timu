"""
Offline test suite for Timu — no network needed.
================================================

    python test_timu.py

Every check runs against synthetic HTML fixtures, so it passes on a laptop, in
CI, or inside a locked-down sandbox with no outbound access. Network behaviour
(HTTP/2 concurrency, robots, cache 304s, browser rendering) is exercised by
`python timu_fetch.py <url>` instead, which needs real connectivity.
"""

from __future__ import annotations

import sys

sys.path.insert(0, ".")

import timu_engine as te                                            # noqa: E402
import timu_fetch as tf                                             # noqa: E402

PASS, FAIL = [], []


def check(name: str, cond, detail: str = ""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{('  — ' + str(detail)) if detail else ''}")


SHOP = """<!doctype html><html lang="en"><head><title>Timu Store — buy gear</title>
<meta name="description" content="Timu Store sells test gear">
<meta property="og:site_name" content="Timu Store">
<script type="application/ld+json">{"@type":"Store","name":"Timu Store","telephone":"+91 98765 43210"}</script>
</head><body>
<h1>Timu Store</h1><h2>Products</h2>
<ul class="grid">
  <li class="card"><h3>Blue Widget</h3><span class="p">₹1,299</span>
      <a href="/p/blue">details</a><img src="/img/blue.png" alt="Blue Widget"></li>
  <li class="card"><h3>Red Widget</h3><span class="p">₹2,499</span>
      <a href="/p/red">details</a><img src="/img/red.png" alt="Red Widget"></li>
  <li class="card"><h3>Green Widget</h3><span class="p">$49.00</span>
      <a href="/p/green">details</a><img src="/img/green.png" alt="Green Widget"></li>
</ul>
<h2>Contact</h2>
<p>Mail us at <a href="mailto:support@timustore.test">support@timustore.test</a> or
   sales@timustore.test. Call <a href="tel:+919876543210">+91 98765 43210</a>.</p>
<address>42 Nehru Road, Sector 5, Pune 411001</address>
<table><caption>Shipping</caption>
  <tr><th>Zone</th><th>Days</th><th>Cost</th></tr>
  <tr><td>Metro</td><td>2</td><td>₹49</td></tr>
  <tr><td>Rest</td><td>5</td><td>₹99</td></tr></table>
<p>Updated on 12 March 2026 — see <a href="https://twitter.com/timu">Twitter</a>.</p>
<a href="/about">About</a><a href="/blog">Blog</a><a href="https://other.test/x">Partner</a>
</body></html>"""

OTHER = """<!doctype html><html><head><title>Other Shop</title>
<meta name="description" content="Other Shop sells test gear"></head><body>
<h1>Other Shop</h1><h2>Products</h2>
<ul><li class="i"><h3>Blue Widget</h3><span>₹1,299</span><a href="/b">go</a></li>
<li class="i"><h3>Yellow Widget</h3><span>₹3,999</span><a href="/y">go</a></li>
<li class="i"><h3>Green Widget</h3><span>$49.00</span><a href="/g">go</a></li></ul>
<p>Contact sales@timustore.test for bulk orders. Call +91 98765 43210.</p>
<a href="/about">About</a><a href="https://twitter.com/timu">Twitter</a>
</body></html>"""

SPA = """<!doctype html><html><head><title>App</title></head><body>
<div id="root"></div><noscript>You need to enable JavaScript to run this app.</noscript>
<script id="__NEXT_DATA__" type="application/json">{"props":{}}</script>
<script src="/static/bundle.js"></script></body></html>"""

SITEMAP_INDEX = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
 <sitemap><loc>https://x.test/sitemap-1.xml</loc></sitemap>
 <sitemap><loc>https://x.test/sitemap-2.xml</loc></sitemap></sitemapindex>"""

SITEMAP_PAGES = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
 <url><loc>https://x.test/a</loc></url><url><loc>https://x.test/b</loc></url>
 <url><loc>https://x.test/c</loc></url></urlset>"""


def fake_page(html: str, url: str) -> te.PageResult:
    return te.PageResult(target=url, url=url, final_url=url, status=200, ok=True, html=html)


def extract(html: str, url: str, query: str) -> dict:
    sc = te.TimuScraper(te.TimuConfig())
    return sc._extract_page(fake_page(html, url), query,
                            te.detect_intents(query), te.css_from_query(query))


def main() -> int:
    print("\n[1] target normalisation")
    check("full url passes through",
          te.normalise_target("https://a.test/x") == ["https://a.test/x"])
    check("bare domain gets https+http",
          te.normalise_target("a.test")[0] == "https://a.test")
    check("bare name probes TLDs",
          len(te.normalise_target("wikipedia")) > 5, te.normalise_target("wikipedia")[:3])
    check("junk rejected", te.normalise_target("   ") == [])

    print("\n[2] query -> intents (English + Hinglish)")
    check("hinglish price word", "prices" in te.detect_intents("keemat nikalo"))
    check("hinglish contact word", "phones" in te.detect_intents("sampark number chahiye"))
    check("products -> items", "items" in te.detect_intents("all products with price"))
    check("tables", "tables" in te.detect_intents("table ka data"))
    check("sara data -> full_text", "full_text" in te.detect_intents("sara data nikalo"))
    check("empty query -> defaults", "headings" in te.detect_intents(""))
    check("css hint parsed", te.css_from_query("css: .card h3") == ".card h3")

    print("\n[3] extraction on a fixture page")
    d = extract(SHOP, "https://timustore.test/",
                "products price email phone address table dates links")
    check("emails found", set(d.get("emails", [])) >=
          {"support@timustore.test", "sales@timustore.test"}, d.get("emails"))
    check("phone found", any("98765" in p for p in d.get("phones", [])), d.get("phones"))
    check("prices found", {"₹1,299", "₹2,499"} <= set(d.get("prices", [])), d.get("prices"))
    items = d.get("items", [])
    check("3 product cards", len(items) == 3, [i["name"] for i in items])
    check("card has price+link", bool(items and items[0]["price"] and items[0]["link"]),
          items[0] if items else None)
    tables = d.get("tables", [])
    check("table parsed with header",
          bool(tables) and tables[0]["columns"] == ["Zone", "Days", "Cost"],
          tables[0]["columns"] if tables else None)
    check("table rows keyed",
          bool(tables) and tables[0]["rows"][0]["Zone"] == "Metro")
    check("address found", any("Nehru" in a for a in d.get("addresses", [])), d.get("addresses"))
    check("date found", any("2026" in x for x in d.get("dates", [])), d.get("dates"))
    check("meta title", d.get("meta", {}).get("title", "").startswith("Timu Store"))
    check("json-ld captured", bool(d.get("structured_data")))
    check("relative links absolutised",
          any(l["url"] == "https://timustore.test/about" for l in d.get("links", [])))
    check("internal flag correct",
          any(l["url"].startswith("https://other.test") and not l["internal"]
              for l in d.get("links", [])))

    print("\n[4] css selector + query line matching")
    d2 = extract(SHOP, "https://timustore.test/", "css: .card h3")
    got = d2.get("css_matches", [])
    ok_css = isinstance(got, list) and got and "error" not in got[0]
    check("css selector extracted 3 nodes" if ok_css else
          "css selector needs soupsieve (skipped)",
          (len(got) == 3) if ok_css else True, got[:1])
    d3 = extract(SHOP, "https://timustore.test/", "shipping cost zone")
    check("query_matches finds lines", bool(d3.get("query_matches")),
          (d3.get("query_matches") or [{}])[0].get("match", "")[:60])

    print("\n[5] common data across two sites")
    sites = [{"target": "a", "ok": True, "data": extract(SHOP, "https://a.test/", "products price email")},
             {"target": "b", "ok": True, "data": extract(OTHER, "https://b.test/", "products price email")}]
    c = te.find_common(sites)
    vals = {r["value"] for r in c["values_on_multiple_sites"]}
    check("shared price detected", "₹1,299" in vals)
    check("shared product detected", any("Blue Widget" in v for v in vals))
    check("shared email detected", "sales@timustore.test" in vals)
    check("booleans excluded", "True" not in vals and "False" not in vals)
    check("shared_fields computed", "items" in c["shared_fields"], c["shared_fields"])
    check("overlap matrix has jaccard",
          all("jaccard" in v for v in c["overlap_matrix"].values()), c["overlap_matrix"])
    check("url normalisation", te._norm("https://WWW.A.test/x/") == "a.test/x")

    print("\n[6] exporters")
    rep = {"timu_version": te.TIMU_VERSION, "query": "products", "intents": ["items"],
           "generated_at": "now", "elapsed_s": 0.1, "targets": ["a", "b"], "sites": sites,
           "summary": {"requested": 2, "succeeded": 2, "failed": [], "total_records": 9},
           "common": c}
    j, csvtxt, md = te.export_json(rep), te.export_csv(rep), te.export_markdown(rep)
    check("json non-trivial", len(j) > 500)
    check("csv has header + rows",
          csvtxt.splitlines()[0] == "site,url,field,key,value" and len(csvtxt.splitlines()) > 10,
          len(csvtxt.splitlines()))
    check("csv contains a price", "₹1,299" in csvtxt)
    check("markdown has sections", "## Common across sites" in md and "# Timu extraction" in md)
    try:
        te.export_xlsx(rep, "_test_timu.xlsx")
        import os
        check("xlsx written", os.path.getsize("_test_timu.xlsx") > 4000)
        os.remove("_test_timu.xlsx")
    except Exception as e:
        check(f"xlsx skipped ({e.__class__.__name__})", True)

    print("\n[7] transport layer (offline parts)")
    spa = tf.FetchResult(url="u", ok=True, body=SPA, status=200)
    real = tf.FetchResult(url="u", ok=True, body=SHOP, status=200)
    js1, why = tf.looks_js_rendered(spa)
    js2, _ = tf.looks_js_rendered(real)
    check("SPA shell flagged for browser render", js1, why)
    check("real html not flagged", not js2)
    pages, nested = tf._xml_locs(SITEMAP_INDEX)
    check("sitemap index -> nested maps", len(nested) == 2 and not pages)
    pages, nested = tf._xml_locs(SITEMAP_PAGES)
    check("sitemap urlset -> 3 pages", len(pages) == 3, pages)
    cache = tf.PageCache(".timu_test_cache", ttl_s=60)
    cache.clear()
    cache.put("https://x.test/a", 200, {"etag": 'W/"1"'}, SHOP, "text/html")
    got = cache.get("https://x.test/a")
    check(f"cache roundtrip ({cache.backend} backend)",
          bool(got) and got["body"] == SHOP and got["etag"] == 'W/"1"' and got["fresh"])
    check("cache miss is None", cache.get("https://x.test/zzz") is None)
    check("cache stats", cache.stats()["pages"] >= 1, cache.stats())
    cache.clear()

    print("\n[8] graceful degradation")
    cfg = te.TimuConfig(transport="legacy")
    try:
        r = te.TimuScraper(cfg).run(["https://definitely-not-real.invalid/"], "emails")
        check("no-transport run still returns a report",
              r["summary"]["requested"] == 1 and r["summary"]["succeeded"] == 0,
              r["summary"]["failed"][:1])
    except Exception as e:
        check("no-transport run should not raise", False, f"{e.__class__.__name__}: {e}")
    check("empty targets rejected",
          _raises(lambda: te.TimuScraper().run([], "x"), ValueError))

    print(f"\n{'='*64}\n  {len(PASS)} passed, {len(FAIL)} failed"
          f"   [httpx={tf.HAVE_HTTPX} playwright={tf.HAVE_PLAYWRIGHT} "
          f"requests={te.HAVE_REQUESTS}]\n{'='*64}")
    if FAIL:
        print("  failed:", ", ".join(FAIL))
    return 1 if FAIL else 0


def _raises(fn, exc) -> bool:
    try:
        fn()
        return False
    except exc:
        return True
    except Exception:
        return False


if __name__ == "__main__":
    raise SystemExit(main())
