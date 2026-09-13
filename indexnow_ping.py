"""Tell IndexNow about every page on this host.

IndexNow is read by Bing (which also feeds DuckDuckGo, Yahoo and ChatGPT
search), Yandex, Seznam and Naver. Google does not use it; Google reads the
Sitemap lines in robots.txt instead.

The key file sits at the host root (<key>.txt), which is what lets one key
cover the hub and all four member sites under their /<slug>/ paths.
Runs at the end of the weekly hub job. A failure here never fails the job.
"""

import json
import re
import sys
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


def urls_from(sitemap: str) -> list[str]:
    with urllib.request.urlopen(sitemap, timeout=30) as resp:
        xml = resp.read().decode("utf-8")
    return re.findall(r"<loc>\s*(https://[^<\s]+)\s*</loc>", xml)


def main() -> None:
    key = find_key()
    urls: list[str] = []
    for sitemap in SITEMAPS:
        try:
            found = [u for u in urls_from(sitemap) if u.startswith(f"https://{HOST}/")]
        except Exception as exc:  # one broken sitemap should not stop the rest
            print(f"[WARN] {sitemap}: {exc}")
            continue
        print(f"[OK] {sitemap}: {len(found)} URLs")
        urls.extend(found)

    urls = list(dict.fromkeys(urls))
    if not urls:
        sys.exit("[FAIL] no URLs collected")

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
