#!/usr/bin/env python3
"""
Download laws/regulations from China's National Laws and Regulations Database.

Modes:
  Search:       python download.py --search "出租车" [--page 1] [--size 20] [--exact]
  Search URLs:  python download.py --search "出租车" --urls-only [--format docx|pdf] [--size 100] [--exact]
  Detail:       python download.py --info <bbbs_id>
  Download:     python download.py --download <bbbs_id> [--format docx|pdf] [output]
  Direct URL:   python download.py <file_url> [output]

Environment:
  SSL verification is disabled by default because the site certificate chain
  is sometimes rejected by default trust stores. To enable it:
    export NPC_LAW_VERIFY_SSL=1

Examples:
  python download.py --search "出租车"
  python download.py --search "物业管理条例" --exact
  python download.py --search "出租车" --urls-only --size 100 > urls.json
  python download.py --info "2c909fdd678bf17901678bf73ebd064f"
  python download.py --download "ff80808172b5f24f0172d9f04f0910af" --format docx 出租车条例.doc
"""

import argparse
import json
import os
import re
import sys
import time

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = "https://flk.npc.gov.cn"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://flk.npc.gov.cn/",
    "Accept": "application/json, text/plain, */*",
}
VERIFY_SSL = os.getenv("NPC_LAW_VERIFY_SSL", "0") == "1"
MAX_RETRIES = 3
BACKOFF = 1.0


def _request(method, url, **kwargs):
    """Make a request with retries and common defaults."""
    kwargs.setdefault("headers", HEADERS)
    kwargs.setdefault("timeout", 30)
    kwargs.setdefault("verify", VERIFY_SSL)
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.request(method, url, **kwargs)
            if resp.status_code < 500:
                return resp
            last_err = f"HTTP {resp.status_code}"
        except requests.RequestException as e:
            last_err = str(e)
        if attempt < MAX_RETRIES:
            time.sleep(BACKOFF * attempt)
    raise RuntimeError(f"Request failed after {MAX_RETRIES} attempts: {last_err}")


def search_laws(keyword: str, page: int = 1, size: int = 20, search_range: int = 1, search_type: int = 2) -> dict:
    """Search laws by keyword. search_range: 1=title, 2=content. search_type: 1=exact, 2=fuzzy."""
    payload = {
        "searchRange": search_range,
        "sxrq": [],
        "gbrq": [],
        "sxx": [],
        "searchType": search_type,
        "xgzlSearch": False,
        "searchContent": keyword,
        "orderByParam": {"order": "-1", "sort": ""},
        "flfgCodeId": [],
        "zdjgCodeId": [],
        "gbrqYear": [],
        "pageNum": page,
        "pageSize": size,
    }
    resp = _request(
        "POST",
        f"{BASE_URL}/law-search/search/list",
        json=payload,
        headers={**HEADERS, "Referer": f"{BASE_URL}/search", "Content-Type": "application/json"},
    )
    return resp.json()


def fetch_detail(bbbs_id: str) -> dict:
    """Fetch detail info for a law by its bbbs ID. Returns parsed JSON or empty dict."""
    try:
        resp = _request(
            "GET",
            f"{BASE_URL}/law-search/search/flfgDetails",
            params={"bbbs": bbbs_id},
        )
        return resp.json() if resp.status_code == 200 else {}
    except Exception as e:
        print(f"Error fetching detail: {e}", file=sys.stderr)
        return {}


def parse_detail(data: dict) -> dict:
    """Extract useful fields from detail API response."""
    if not data or data.get("code") != 200:
        return {}
    d = data.get("data", {})
    oss = d.get("ossFile", {}) or {}
    return {
        "bbbs": d.get("bbbs", ""),
        "title": d.get("title", "Unknown"),
        "category": d.get("flxz", ""),
        "authority": d.get("zdjgName", ""),
        "publish_date": d.get("gbrq", ""),
        "effective_date": d.get("sxrq", ""),
        "status_code": d.get("sxx", 0),
        "word_url": f"{BASE_URL}/{oss['ossWordPath']}" if oss.get("ossWordPath") else None,
        "pdf_url": f"{BASE_URL}/{oss['ossPdfPath']}" if oss.get("ossPdfPath") else None,
        "word_ofd_url": f"{BASE_URL}/{oss['ossWordOfdPath']}" if oss.get("ossWordOfdPath") else None,
        "pdf_ofd_url": f"{BASE_URL}/{oss['ossPdfOfdPath']}" if oss.get("ossPdfOfdPath") else None,
    }


def get_download_url(bbbs_id: str, fmt: str = "docx") -> str:
    """Get a signed download URL from the official download API."""
    resp = _request(
        "GET",
        f"{BASE_URL}/law-search/download/pc",
        params={"format": fmt, "bbbs": bbbs_id},
        headers={**HEADERS, "Referer": f"{BASE_URL}/detail?id={bbbs_id}"},
    )
    data = resp.json()
    if data.get("code") != 200:
        raise RuntimeError(f"Download API error: {data.get('msg')}")
    url = data.get("data", {}).get("url")
    if not url:
        raise RuntimeError(f"No download URL returned for format={fmt}")
    return url


def download_file(url: str, output_path: str = None) -> str:
    """Download a file from URL. Returns saved path or raises on failure."""
    resp = _request("GET", url)
    resp.raise_for_status()

    ct = resp.headers.get("Content-Type", "")
    if "text/html" in ct and len(resp.content) < 5000:
        raise RuntimeError(f"Server returned HTML page instead of file (size: {len(resp.content)} bytes)")

    if not output_path:
        cd = resp.headers.get("Content-Disposition", "")
        fname_match = re.search(r'filename="?([^"]+)"?', cd)
        output_path = fname_match.group(1) if fname_match else url.split("/")[-1].split("?")[0]

    os.makedirs(os.path.dirname(os.path.abspath(output_path)) if os.path.dirname(output_path) else ".", exist_ok=True)

    with open(output_path, "wb") as f:
        f.write(resp.content)

    print(f"Downloaded: {output_path} ({len(resp.content)} bytes)")
    return output_path


def print_detail(info: dict):
    """Print law detail information in readable format."""
    if not info:
        print("Failed to fetch detail")
        return
    print(f"Title: {info['title']}")
    print(f"Category: {info['category']}")
    print(f"Authority: {info['authority']}")
    print(f"Publish Date: {info['publish_date']}")
    print(f"Effective Date: {info['effective_date']}")
    print(f"Status Code: {info['status_code']}")
    print(f"BBBS: {info['bbbs']}")
    print("\nDownload URLs:")
    for key in ("word_url", "pdf_url", "word_ofd_url", "pdf_ofd_url"):
        if info.get(key):
            print(f"  {key}: {info[key]}")


def print_search_results(data: dict):
    """Print search results in a compact table."""
    if data.get("code") != 200:
        print(f"Search failed: {data.get('msg')}")
        return
    rows = data.get("rows", [])
    total = data.get("total", 0)
    print(f"Total: {total} | Returned: {len(rows)}")
    for row in rows:
        title = re.sub(r"<[^>]+>", "", row.get("title", ""))
        print(f"- {title}")
        print(f"  bbbs: {row.get('bbbs')}")
        print(f"  category: {row.get('flxz')} | authority: {row.get('zdjgName')}")
        print(f"  publish: {row.get('gbrq')} | effective: {row.get('sxrq')} | status: {row.get('sxx')}")


def collect_search_urls(data: dict, fmt: str = "docx") -> list:
    """Return search results enriched with signed download URLs as JSON."""
    results = []
    rows = data.get("rows", []) if data.get("code") == 200 else []
    for row in rows:
        bbbs = row.get("bbbs")
        item = {
            "bbbs": bbbs,
            "title": re.sub(r"<[^>]+>", "", row.get("title", "")),
            "category": row.get("flxz"),
            "authority": row.get("zdjgName"),
            "publish_date": row.get("gbrq"),
            "effective_date": row.get("sxrq"),
            "status_code": row.get("sxx"),
            "format": fmt,
            "url": None,
            "error": None,
        }
        try:
            item["url"] = get_download_url(bbbs, fmt)
        except Exception as e:
            item["error"] = str(e)
        results.append(item)
    return results


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="download.py",
        description="Download laws/regulations from China's National Laws and Regulations Database.",
        epilog="For batch collection see references/batch_collection.md",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--info", metavar="BBBS_ID", help="Fetch detail info for a law")
    mode.add_argument("--search", metavar="KEYWORD", help="Search laws by keyword")
    mode.add_argument("--download", metavar="BBBS_ID", help="Download a single law")

    parser.add_argument("--page", type=int, default=1, help="Search page number (default: 1)")
    parser.add_argument("--size", type=int, default=20, help="Search page size (default: 20)")
    parser.add_argument("--urls-only", action="store_true", help="Output signed URLs instead of downloading")
    parser.add_argument("--format", default="docx", choices=["docx", "pdf"], help="Download format (default: docx)")
    parser.add_argument("--exact", action="store_true", help="Use exact title match for search")
    parser.add_argument("output", nargs="?", help="Output path for --download or direct URL mode")
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    # Determine mode: direct URL if no flag but positional output/URL provided
    if not any([args.info, args.search, args.download]):
        if not args.output:
            parser.print_help()
            sys.exit(1)
        if not args.output.startswith(("http://", "https://")):
            parser.error("Direct mode requires a URL starting with http:// or https://")
        download_file(args.output, None)
        return

    if args.info:
        raw = fetch_detail(args.info)
        print_detail(parse_detail(raw))

    elif args.search:
        search_type = 1 if args.exact else 2
        data = search_laws(args.search, page=args.page, size=args.size, search_type=search_type)
        if args.urls_only:
            enriched = collect_search_urls(data, args.format)
            json.dump(enriched, sys.stdout, ensure_ascii=False, indent=2)
            print()
        else:
            print_search_results(data)

    elif args.download:
        url = get_download_url(args.download, args.format)
        download_file(url, args.output)


if __name__ == "__main__":
    main()
