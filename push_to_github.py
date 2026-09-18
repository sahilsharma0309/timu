"""
push_to_github.py — publish this folder to a GitHub repo in one commit.
=======================================================================

Stdlib only (urllib + json), so it runs anywhere Python runs — no git binary,
no pip install, no PyGithub.

    set GITHUB_TOKEN=ghp_...            (Windows)     token needs: Contents write
    export GITHUB_TOKEN=ghp_...         (macOS/Linux) and, to create the repo,
                                                      Administration write
    python push_to_github.py --owner sahilsharma0309 --repo timu

Options
-------
    --owner   GitHub username (required)
    --repo    repository name (default: timu)
    --branch  branch to push (default: main)
    --message commit message
    --create  try to create the repo if it does not exist
    --private create it private (with --create)
    --dry-run list what would be pushed and exit

Existing files with the same path are overwritten by this commit; anything else
in the repo is left untouched (the previous tree is used as the base).
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

API = "https://api.github.com"

# repo path -> local path
FILES: dict[str, str] = {
    "README.md": "README.md",
    "LICENSE": "LICENSE",
    ".gitignore": ".gitignore",
    "requirements.txt": "requirements.txt",
    "packages.txt": "packages.txt",
    "assets/timu_logo.svg": "timu_logo.svg",
    "streamlit_app.py": "streamlit_app.py",
    "timu_app.py": "timu_app.py",
    "timu_ui.html": "timu_ui.html",
    "timu_engine.py": "timu_engine.py",
    "timu_fetch.py": "timu_fetch.py",
    "timu_doctor.py": "timu_doctor.py",
    "test_timu.py": "test_timu.py",
    "push_to_github.py": "push_to_github.py",
    "github_push.bat": "github_push.bat",
    "github_push.sh": "github_push.sh",
    "run_timu.bat": "run_timu.bat",
    "run_timu.sh": "run_timu.sh",
    ".streamlit/config.toml": "_streamlit_config.toml",
    ".github/workflows/tests.yml": "_ci_tests.yml",
    "docs/README_HINGLISH.md": "README_TIMU.md",
    "examples/timu_demo_report.json": "timu_demo_report.json",
    "examples/timu_demo_report.csv": "timu_demo_report.csv",
    "examples/timu_demo_report.md": "timu_demo_report.md",
    "examples/timu_demo_report.xlsx": "timu_demo_report.xlsx",
}
EXEC_BITS = {"run_timu.sh", "github_push.sh"}          # pushed with mode 100755


def call(path: str, token: str, method: str = "GET", body: dict | None = None):
    req = urllib.request.Request(
        API + path, method=method,
        data=None if body is None else json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {token}",
                 "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28",
                 "Content-Type": "application/json",
                 "User-Agent": "timu-push"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except Exception:
            return e.code, {}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--owner", required=True)
    ap.add_argument("--repo", default="timu")
    ap.add_argument("--branch", default="main")
    ap.add_argument("--message", default="Timu v2 — extraction engine, transport layer, "
                                         "Streamlit + Flask UIs, tests")
    ap.add_argument("--create", action="store_true")
    ap.add_argument("--private", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    here = Path(__file__).resolve().parent
    present = {rp: here / lp for rp, lp in FILES.items() if (here / lp).exists()}
    absent = [lp for lp in FILES.values() if not (here / lp).exists()]
    total = sum(p.stat().st_size for p in present.values())
    print(f"{len(present)} file(s), {total/1024:.1f} KiB")
    for rp in sorted(present):
        print(f"   {rp:<38} {present[rp].stat().st_size:>8} B")
    if absent:
        print("missing locally (skipped):", ", ".join(sorted(absent)))
    if a.dry_run:
        return 0

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
    if not token:
        print("\nGITHUB_TOKEN not set. Create a token with `Contents: write` on the repo:")
        print("  https://github.com/settings/personal-access-tokens")
        return 2

    st, me = call("/user", token)
    if st != 200:
        print(f"token rejected ({st}): {me.get('message')}")
        return 2
    print(f"authenticated as {me.get('login')}")

    st, repo = call(f"/repos/{a.owner}/{a.repo}", token)
    if st == 404:
        if not a.create:
            print(f"\nrepo {a.owner}/{a.repo} does not exist.")
            print("Create it empty (no README / .gitignore / license) here:")
            print(f"  https://github.com/new?name={a.repo}")
            print("…then run this script again. Or pass --create with a token that has "
                  "`Administration: write`.")
            return 3
        st, repo = call("/user/repos", token, "POST",
                        {"name": a.repo, "private": bool(a.private), "auto_init": False,
                         "description": "Timu — query-driven web data extraction agent"})
        if st != 201:
            print(f"could not create repo ({st}): {repo.get('message')}")
            print("Your token likely lacks `Administration: write`. Create the empty repo "
                  f"by hand: https://github.com/new?name={a.repo}")
            return 3
        print(f"created {repo.get('full_name')}")
    elif st != 200:
        print(f"cannot read repo ({st}): {repo.get('message')}")
        return 3

    # base commit (if the branch already exists)
    base_tree, parents = None, []
    st, ref = call(f"/repos/{a.owner}/{a.repo}/git/ref/heads/{a.branch}", token)
    if st == 200:
        head = ref["object"]["sha"]
        parents = [head]
        st_c, commit = call(f"/repos/{a.owner}/{a.repo}/git/commits/{head}", token)
        base_tree = commit["tree"]["sha"] if st_c == 200 else None
        print(f"branch {a.branch} exists at {head[:8]} — adding a commit on top")
    else:
        print(f"branch {a.branch} does not exist yet — creating it")

    # blobs
    tree = []
    for rp, lp in sorted(present.items()):
        raw = lp.read_bytes()
        st_b, blob = call(f"/repos/{a.owner}/{a.repo}/git/blobs", token, "POST",
                          {"content": base64.b64encode(raw).decode(), "encoding": "base64"})
        if st_b != 201:
            print(f"blob failed for {rp} ({st_b}): {blob.get('message')}")
            return 4
        tree.append({"path": rp, "mode": "100755" if rp in EXEC_BITS else "100644",
                     "type": "blob", "sha": blob["sha"]})
        print(f"   blob ok  {rp}")

    payload = {"tree": tree}
    if base_tree:
        payload["base_tree"] = base_tree
    st_t, tree_obj = call(f"/repos/{a.owner}/{a.repo}/git/trees", token, "POST", payload)
    if st_t != 201:
        print(f"tree failed ({st_t}): {tree_obj.get('message')}")
        return 4

    st_c, commit = call(f"/repos/{a.owner}/{a.repo}/git/commits", token, "POST",
                        {"message": a.message, "tree": tree_obj["sha"], "parents": parents})
    if st_c != 201:
        print(f"commit failed ({st_c}): {commit.get('message')}")
        return 4

    if parents:
        st_r, res = call(f"/repos/{a.owner}/{a.repo}/git/refs/heads/{a.branch}", token,
                         "PATCH", {"sha": commit["sha"], "force": False})
    else:
        st_r, res = call(f"/repos/{a.owner}/{a.repo}/git/refs", token, "POST",
                         {"ref": f"refs/heads/{a.branch}", "sha": commit["sha"]})
    if st_r not in (200, 201):
        print(f"ref update failed ({st_r}): {res.get('message')}")
        return 4

    print(f"\npushed {len(tree)} file(s) as {commit['sha'][:8]}")
    print(f"  repo   https://github.com/{a.owner}/{a.repo}")
    print(f"  deploy https://share.streamlit.io  ->  New app  ->  {a.owner}/{a.repo}"
          f"  ->  {a.branch}  ->  streamlit_app.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
