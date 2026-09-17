"""
Timu doctor — what is installed, what works, what is missing.

    python timu_doctor.py              full report
    python timu_doctor.py --chromium   exit 0 if a Chromium build is present, else 1
                                       (the launchers use this to decide whether to ask)
"""

from __future__ import annotations

import importlib
import platform
import sys

CHECKS = [
    ("bs4", "beautifulsoup4", "HTML parsing", True),
    ("soupsieve", "soupsieve", "`css:` selector queries", False),
    ("lxml", "lxml", "faster HTML parser", False),
    ("httpx", "httpx[http2]", "async HTTP/2 transport (the fast path)", False),
    ("h2", "h2", "HTTP/2 protocol support", False),
    ("flask", "flask", "the browser UI", False),
    ("openpyxl", "openpyxl", "XLSX export", False),
    ("requests", "requests", "legacy sequential fetcher", False),
    ("playwright", "playwright", "JavaScript rendering", False),
]


def probe(mod: str) -> tuple[bool, str]:
    try:
        m = importlib.import_module(mod)
        return True, str(getattr(m, "__version__", "") or "ok")
    except Exception as e:
        return False, f"{e.__class__.__name__}: {str(e)[:60]}"


def chromium_present() -> tuple[bool, str]:
    try:
        import timu_fetch as tf
        return tf.chromium_available()
    except Exception as e:
        return False, f"timu_fetch not importable ({e.__class__.__name__})"


def main(argv: list[str]) -> int:
    if "--chromium" in argv:
        ok, _ = chromium_present()
        return 0 if ok else 1

    print(f"\nTimu doctor — python {platform.python_version()} on "
          f"{platform.system()} {platform.machine()}\n" + "-" * 66)
    missing_required, missing_optional = [], []
    for mod, pkg, why, required in CHECKS:
        ok, info = probe(mod)
        mark = "ok  " if ok else ("MISS" if required else "----")
        print(f"  [{mark}] {mod:<12} {info[:22]:<24} {why}")
        if not ok:
            (missing_required if required else missing_optional).append(pkg)

    ok, info = chromium_present()
    print(f"  [{'ok  ' if ok else '----'}] chromium     "
          f"{('present' if ok else 'missing'):<24} "
          f"{'browser render available' if ok else info[:60]}")

    try:
        import timu_fetch as tf
        c = tf.PageCache(".timu_cache")
        print(f"\n  cache backend : {c.backend}  ({c.stats()['pages']} pages stored)")
        print(f"  transport     : {'async HTTP/2' if tf.HAVE_HTTPX else 'legacy requests only'}")
    except Exception as e:
        print(f"\n  timu_fetch not importable: {e.__class__.__name__}: {e}")

    try:
        import timu_engine as te
        print(f"  engine        : v{te.TIMU_VERSION}  "
              f"({len(te.EXTRACTORS)} extractors, max {te.MAX_TARGETS} targets)")
    except Exception as e:
        print(f"  timu_engine not importable: {e.__class__.__name__}: {e}")

    print("-" * 66)
    if missing_required:
        print("  install (required):  pip install " + " ".join(missing_required))
    if missing_optional:
        print("  install (optional):  pip install " + " ".join(missing_optional))
    if not ok:
        print("  browser render   :  python -m playwright install chromium")
    if not missing_required and ok:
        print("  everything Timu needs is present.")
    print()
    return 1 if missing_required else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
