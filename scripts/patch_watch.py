#!/usr/bin/env python3
"""Watch Project Reforged's downloads and refresh meta/patch-manifest.json.

Full design: claude/patch-updates-plan.md in the Bear Dog Launcher project docs.
The rules that matter when editing this file:

  * The ETag is a CHANGE BOOKMARK, never an integrity check. Most of these are
    R2 multipart ETags (the "-167" suffix), which are a hash of part hashes, not
    the file's MD5. Never write one into the sha256 field, never compare one to
    a sha256.
  * sha256 is the contract the launcher enforces. It is ALWAYS computed here
    from bytes this script actually downloaded and counted. It is never copied
    from a header, a cache, or the old manifest.
  * A normal day downloads nothing: 11 HEAD requests, no writes, exit 0. If this
    script starts producing a pull request every day, something is wrong with it,
    not with upstream.
  * Version strings are cosmetic. A scraper failure must never block a real byte
    update, and must never fail the run.

Usage:
    python3 scripts/patch_watch.py --manifest meta/patch-manifest.json
    python3 scripts/patch_watch.py --check      # HEAD only: no downloads, no writes
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request
from typing import Any

PAGE_URL = "https://projectreforged.github.io/vanilla/downloads/turtle/"
USER_AGENT = "bear-dog-launcher-patch-watch/1 (+https://github.com/lorgeandinchorge/beardog-content)"
CHUNK = 1024 * 1024

# A downloaded patch smaller than this is almost certainly an error page or a
# truncated transfer rather than a real MPQ. Not fatal - the sha256 still gets
# computed honestly and Paul still reviews the PR - but it is called out loudly.
SUSPICIOUS_MIN_BYTES = 1024 * 1024


def log(msg: str) -> None:
    print(msg, flush=True)


class HttpsOnlyRedirect(urllib.request.HTTPRedirectHandler):
    """Mirror the launcher's rule: never follow a redirect off https."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not newurl.lower().startswith("https://"):
            raise RuntimeError(f"refusing redirect to non-https URL: {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


OPENER = urllib.request.build_opener(HttpsOnlyRedirect)


def request(url: str, method: str = "GET"):
    req = urllib.request.Request(url, method=method, headers={"User-Agent": USER_AGENT})
    return OPENER.open(req, timeout=60)


def head(url: str, attempts: int = 3) -> dict[str, str]:
    """HEAD with a short retry.

    This runs unattended every day. A single dropped connection should not fail
    the run and mail Paul about it - but a persistent failure still must, because
    "I could not check" is never allowed to look like "nothing changed".
    """
    last: Exception | None = None
    for i in range(attempts):
        try:
            with request(url, "HEAD") as resp:
                return {
                    "status": str(resp.status),
                    "etag": resp.headers.get("ETag", "") or "",
                    "size": resp.headers.get("Content-Length", "") or "",
                    "modified": resp.headers.get("Last-Modified", "") or "",
                    "ranges": resp.headers.get("Accept-Ranges", "") or "",
                }
        except Exception as exc:  # noqa: BLE001 - retried, then re-raised
            last = exc
            if i + 1 < attempts:
                time.sleep(2**i)
    raise last  # type: ignore[misc]


def download_and_hash(url: str) -> tuple[int, str]:
    """Stream to a temp file, hashing as we go, then delete it.

    The file is never kept. patch-C alone is 2.08 GB against a runner's ~14 GB of
    free disk, so callers must do one patch at a time.
    """
    digest = hashlib.sha256()
    total = 0
    fd, tmp = tempfile.mkstemp(prefix="patchwatch-", suffix=".mpq")
    try:
        with request(url) as resp, os.fdopen(fd, "wb") as out:
            while True:
                block = resp.read(CHUNK)
                if not block:
                    break
                out.write(block)
                digest.update(block)
                total += len(block)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    return total, digest.hexdigest()


def scrape_versions(patches: list[dict[str, Any]]) -> dict[str, str]:
    """Best-effort version strings from the downloads page. Never raises."""
    try:
        with request(PAGE_URL) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001 - cosmetic data, never fatal
        log(f"  version scrape: page unavailable ({exc}); keeping recorded versions")
        return {}

    found: dict[str, str] = {}
    for p in patches:
        idx = html.find(p["url"])
        if idx < 0:
            continue
        window = html[max(0, idx - 600) : idx + 600]
        m = re.search(r"[vV]?(\d+\.\d+\.\d+)", window)
        if m:
            found[p["id"]] = m.group(1)
    if not found:
        log("  version scrape: no versions matched; page layout may have changed")
    return found


def emit_output(name: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(f"{name}={value}\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default="meta/patch-manifest.json")
    ap.add_argument("--pr-body", default="")
    ap.add_argument(
        "--check",
        action="store_true",
        help="HEAD only: report what moved, download nothing, write nothing.",
    )
    args = ap.parse_args()

    with open(args.manifest, encoding="utf-8") as fh:
        manifest = json.load(fh)

    allowed = set(manifest.get("allowed_hosts", []))
    if not allowed:
        log("FATAL: manifest declares no allowed_hosts")
        return 2

    patches = manifest["patches"]
    log(f"Checking {len(patches)} patches against {sorted(allowed)}")

    moved: list[dict[str, Any]] = []
    failures: list[str] = []

    for p in patches:
        url = p["url"]
        if not url.startswith("https://"):
            failures.append(f"{p['id']}: url is not https")
            continue
        host = url.split("/")[2]
        if host not in allowed:
            failures.append(f"{p['id']}: host {host} is not in allowed_hosts")
            continue

        try:
            h = head(url)
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{p['id']}: HEAD failed ({exc})")
            continue

        same_etag = bool(h["etag"]) and h["etag"] == p.get("etag", "")
        same_size = h["size"].isdigit() and int(h["size"]) == p.get("size")

        if same_etag and same_size:
            log(f"  {p['id']:<12} unchanged")
            continue
        if not h["etag"]:
            # No bookmark to compare. Size is the only signal we have left.
            if same_size:
                log(f"  {p['id']:<12} unchanged (no ETag; size matched)")
                continue
            log(f"  {p['id']:<12} CHANGED (no ETag; size differs)")
        else:
            log(f"  {p['id']:<12} CHANGED  etag {p.get('etag','')} -> {h['etag']}")

        moved.append({"patch": p, "head": h})

    if failures:
        for f in failures:
            log(f"FAILED: {f}")
        # A HEAD failure is not a reason to publish a half-checked manifest.
        log("Refusing to continue with incomplete information.")
        return 1

    if not moved:
        log("Nothing moved. No downloads, no changes.")
        emit_output("changed", "false")
        return 0

    if args.check:
        log(f"--check: {len(moved)} patch(es) would be downloaded and rehashed.")
        emit_output("changed", "true")
        return 0

    versions = scrape_versions([m["patch"] for m in moved])

    lines: list[str] = []
    titles: list[str] = []
    for m in moved:
        p, h = m["patch"], m["head"]
        log(f"Downloading {p['id']} ({h['size'] or 'unknown'} bytes)...")
        size, sha = download_and_hash(p["url"])

        if h["size"].isdigit() and int(h["size"]) != size:
            log(f"FATAL: {p['id']} Content-Length said {h['size']}, received {size}")
            return 1
        if sha == p.get("sha256"):
            # Bytes are identical despite a new ETag - R2 re-upload, not a new
            # build. Refresh the bookmark so we stop re-downloading it, but say
            # so plainly rather than pretending it is an update.
            log(f"  {p['id']}: ETag moved but bytes are identical; bookmark only")
            p["etag"] = h["etag"]
            p["upstream_modified"] = h["modified"]
            lines.append(f"- `{p['id']}` - re-uploaded upstream, **contents unchanged** (bookmark refreshed)")
            continue

        old_size, old_ver = p.get("size"), p.get("version", "")
        new_ver = versions.get(p["id"], old_ver)

        note = ""
        if size < SUSPICIOUS_MIN_BYTES:
            note = "  **SUSPICIOUSLY SMALL - inspect before merging**"
        elif isinstance(old_size, int) and old_size and size < old_size * 0.5:
            note = f"  **shrank by more than half ({old_size} -> {size}) - worth a look**"

        p["size"] = size
        p["sha256"] = sha
        p["etag"] = h["etag"]
        p["upstream_modified"] = h["modified"]
        p["version"] = new_ver
        p["seen"] = h["modified"] or p.get("seen", "")

        vtxt = f"{old_ver} -> {new_ver}" if new_ver != old_ver else f"{new_ver} (version text unchanged)"
        titles.append(f"{p['target'].split('/')[-1]} {vtxt}")
        lines.append(
            f"- `{p['id']}` ({p['target']}) {vtxt}\n"
            f"  - size `{old_size}` -> `{size}`\n"
            f"  - sha256 `{sha}`\n"
            f"  - upstream modified {h['modified']}{note}"
        )

    with open(args.manifest, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    title = "patch-watch: " + (", ".join(titles) if titles else "refresh upstream bookmarks")
    if len(title) > 72:
        title = f"patch-watch: {len(titles) or len(lines)} patch(es) updated"

    body = (
        "Automated by `.github/workflows/patch-watch.yml`.\n\n"
        "Every `sha256` below was computed from bytes this run downloaded in full "
        "and counted against `Content-Length`. ETags are change bookmarks only - "
        "most are R2 multipart hashes and are not file digests.\n\n"
        "## What moved\n\n" + "\n".join(lines) + "\n\n"
        "## Before merging\n\n"
        "- Version strings are scraped from the downloads page and are cosmetic; "
        "the launcher never makes a decision from them.\n"
        "- Merging this publishes the update to every teammate on their next sync.\n"
    )

    log("\n" + body)
    if args.pr_body:
        with open(args.pr_body, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(body)

    emit_output("changed", "true")
    emit_output("title", title)
    return 0


if __name__ == "__main__":
    sys.exit(main())
