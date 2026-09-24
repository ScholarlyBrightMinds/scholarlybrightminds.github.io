"""Tell IndexNow about the pages on this host that changed this week.

IndexNow is read by Bing (which also feeds DuckDuckGo, Yahoo and ChatGPT
search), Yandex, Seznam and Naver. Google does not use it; Google reads the
Sitemap lines in robots.txt instead.

The key file sits at the host root (<key>.txt), which is what lets one key
cover the hub and all four member sites under their /<slug>/ paths.
Runs at the end of the weekly hub job. A failure here never fails the job.

Only URLs whose sitemap <lastmod> falls in the last 8 days are sent. The
IndexNow FAQ asks for changed URLs only, and resubmitting unchanged ones can
earn a 422 and waste the crawl budget the key gets. Pages without a lastmod
are not resent; they were all submitted before and stay in the sitemaps.
`python indexnow_ping.py --all` sends every URL once, for a one-off.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
import urllib.error
import urllib.request
from pathlib import Path

HOST = "scholarlybrightminds.github.io"
SITEMAPS = [
    f"https://{HOST}/sitemap.xml",
    f"https://{HOST}/abdallahabouhajal/sitemap.xml",
    f"https://{HOST}/molhamsakkal/sitemap.xml",
    f"https://{HOST}/Rahafalzeer/sitemap.xml",
    f"https://{HOST}/ahmadalmeslamani/sitemap.xml",
]


def find_key() -> str:
    for path in Path(__file__).resolve().parent.glob("*.txt"):
        if re.fullmatch(r"[0-9a-f]{32}", path.stem) and path.read_text().strip() == path.stem:
            return path.stem
    sys.exit("[FAIL] no IndexNow key file found at the repo root")


WINDOW_DAYS = 8   # the job runs weekly; a day of slack for late runs


def urls_from(sitemap: str) -> list[tuple[str, date | None]]:
    """(url, lastmod) for every <url> in the sitemap; lastmod may be absent."""
    with urllib.request.urlopen(sitemap, timeout=30) as resp:
        xml = resp.read().decode("utf-8")
    out = []
    for block in re.findall(r"<url>(.*?)</url>", xml, re.S):
        loc = re.search(r"<loc>\s*(https://[^<\s]+)\s*</loc>", block)
        if not loc:
            continue
        lm = re.search(r"<lastmod>\s*(\d{4}-\d{2}-\d{2})", block)
        out.append((loc.group(1), date.fromisoformat(lm.group(1)) if lm else None))
    return out


def main() -> None:
    key = find_key()
    send_all = "--all" in sys.argv
    since = datetime.now(timezone.utc).date() - timedelta(days=WINDOW_DAYS)
    urls: list[str] = []
    for sitemap in SITEMAPS:
        try:
            found = [(u, lm) for u, lm in urls_from(sitemap) if u.startswith(f"https://{HOST}/")]
        except Exception as exc:  # one broken sitemap should not stop the rest
            print(f"[WARN] {sitemap}: {exc}")
            continue
        fresh = [u for u, lm in found if send_all or (lm is not None and lm >= since)]
        print(f"[OK] {sitemap}: {len(found)} URLs, {len(fresh)} to send")
        urls.extend(fresh)

    urls = list(dict.fromkeys(urls))
    if not urls:
        print(f"[OK] nothing changed since {since}, nothing sent")
        return

    body = json.dumps({
        "host": HOST,
        "key": key,
        "keyLocation": f"https://{HOST}/{key}.txt",
        "urlList": urls,
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.indexnow.org/indexnow",
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            print(f"[OK] IndexNow accepted {len(urls)} URLs, HTTP {resp.status}")
    except urllib.error.HTTPError as exc:
        print(f"[WARN] IndexNow answered HTTP {exc.code}: {exc.read()[:200]!r}")


if __name__ == "__main__":
    main()
