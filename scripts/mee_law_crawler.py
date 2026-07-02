#!/usr/bin/env python3
"""
Download/search environmental regulations from the Ministry of Ecology and Environment (生态环境部法规标准).

Source: https://www.mee.gov.cn/ywgz/fgbz/

Categories:
  法律(fl), 行政法规(xzfg), 规章(gzk/gz), 标准(bz)

Usage:
  python mee_law_crawler.py --search "碳" --size 20
  python mee_law_crawler.py --category 标准 --size 50
  python mee_law_crawler.py --category 法律 --size 100
  python mee_law_crawler.py --info "https://www.mee.gov.cn/ywgz/fgbz/fl/202603/t20260313_1146496.shtml"
"""

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urljoin

from common import (
    DEFAULT_USER_AGENT,
    _CacheManager,
    clean_text,
    ensure_dir,
    get_cache,
    http_request,
    init_limiter,
    render_markdown_report,
    sanitize_filename,
    setup_logger,
    write_csv,
    write_json,
    write_jsonl,
    write_text,
)

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

BASE_URL = "https://www.mee.gov.cn"
FG_BASE = f"{BASE_URL}/ywgz/fgbz"

CATEGORY_MAP = {
    "全部": "",
    "法律": "fl",
    "行政法规": "xzfg",
    "规章": "gz",  # actual path is /gzk/gz/
    "标准": "bz",
}

CATEGORY_URLS = {
    "fl": f"{FG_BASE}/fl/",
    "xzfg": f"{FG_BASE}/xzfg/",
    "gz": f"{BASE_URL}/gzk/gz/",  # different base path
    "bz": f"{FG_BASE}/bz/",
}

HEADERS = {
    "User-Agent": DEFAULT_USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

_cache = get_cache("mee-law-db")


# ---------------------------------------------------------------------------
# List page parsing
# ---------------------------------------------------------------------------


def fetch_list_page(url: str, timeout: int = 30):
    """Fetch a category list page."""
    cache_key = _cache._key("list", url)
    cached = _cache.get(cache_key, max_age=3600)
    if cached:
        return cached

    resp = http_request("GET", url, headers=HEADERS, timeout=timeout)
    resp.encoding = "utf-8"
    _cache.set(cache_key, resp.text)
    return resp.text


def parse_list_page(html: str, category: str = "") -> list[dict]:
    """Parse a list page to extract article links."""
    records = []
    if BeautifulSoup is None:
        return records

    soup = BeautifulSoup(html, "html.parser")
    links = soup.find_all("a", href=True)

    seen_urls = set()
    for link in links:
        href = link["href"]
        text = link.get_text(" ", strip=True)

        # Must be an article page (contains /t202... or /t20... pattern)
        if not re.search(r"/t20\d+", href):
            continue
        if len(text) < 5:
            continue

        full_url = urljoin(BASE_URL, href)
        if full_url in seen_urls:
            continue
        seen_urls.add(full_url)

        # Determine sub-category from URL if not provided
        sub_cat = category
        if not sub_cat:
            if "/fl/" in href:
                sub_cat = "fl"
            elif "/xzfg/" in href:
                sub_cat = "xzfg"
            elif "/gzk/" in href or "/gz/" in href:
                sub_cat = "gz"
            elif "/bz/" in href:
                sub_cat = "bz"

        records.append(
            {
                "source": "mee_law",
                "category": sub_cat,
                "title": clean_text(text),
                "url": full_url,
            }
        )

    return records


# ---------------------------------------------------------------------------
# Detail page parsing
# ---------------------------------------------------------------------------


def fetch_detail(detail_url: str, timeout: int = 30) -> dict:
    """Fetch and parse an article detail page."""
    cache_key = _cache._key("detail", detail_url)
    cached = _cache.get(cache_key, max_age=86400)
    if cached:
        return cached

    resp = http_request("GET", detail_url, headers=HEADERS, timeout=timeout)
    resp.encoding = "utf-8"

    result = {
        "url": detail_url,
        "title": "",
        "content_text": "",
        "publish_date": "",
    }

    if BeautifulSoup is not None:
        soup = BeautifulSoup(resp.text, "html.parser")

        title_node = (
            soup.select_one("h1")
            or soup.select_one(".article-title")
            or soup.select_one(".title")
            or soup.select_one("h2")
            or soup.select_one(".bt")
        )
        if title_node:
            result["title"] = clean_text(title_node.get_text(" ", strip=True))

        content_node = (
            soup.select_one(".article-content")
            or soup.select_one(".content")
            or soup.select_one("#content")
            or soup.select_one(".pages_content")
            or soup.select_one(".TRS_Editor")
            or soup.select_one(".con_text")
            or soup.select_one("main")
            or soup.select_one("article")
        )
        if content_node:
            result["content_text"] = clean_text(content_node.get_text("\n", strip=True))

        date_node = (
            soup.select_one(".date")
            or soup.select_one(".time")
            or soup.select_one(".pub-date")
            or soup.select_one(".publish-time")
            or soup.select_one(".sj")
        )
        if date_node:
            result["publish_date"] = clean_text(date_node.get_text(" ", strip=True))

        # Try to find date in URL path
        if not result["publish_date"]:
            date_match = re.search(r"/(t20\d{2})(\d{2})(\d{2})", detail_url)
            if date_match:
                result["publish_date"] = (
                    f"{date_match.group(1)[1:5]}-{date_match.group(2)}-{date_match.group(3)}"
                )

    _cache.set(cache_key, result)
    return result


# ---------------------------------------------------------------------------
# Search and collect
# ---------------------------------------------------------------------------


def search_keyword_in_records(records: list[dict], keyword: str) -> list[dict]:
    """Filter records whose title matches keyword."""
    if not keyword:
        return records
    kw = keyword.lower()
    return [r for r in records if kw in r["title"].lower()]


def search_collect(
    keyword: str = "", category: str = "", max_items: int = 20, timeout: int = 30
) -> list[dict]:
    """Search and collect environmental regulations."""
    records = []
    cat_key = CATEGORY_MAP.get(category, "")

    if cat_key:
        categories_to_fetch = [cat_key]
    else:
        categories_to_fetch = list(CATEGORY_URLS.keys())

    for cat in categories_to_fetch:
        if len(records) >= max_items:
            break

        url = CATEGORY_URLS.get(cat, f"{FG_BASE}/{cat}/")
        html = fetch_list_page(url, timeout=timeout)
        items = parse_list_page(html, category=cat)

        if keyword:
            items = search_keyword_in_records(items, keyword)

        for item in items:
            if len(records) >= max_items:
                break
            records.append(item)

    return records


# ---------------------------------------------------------------------------
# Output / report
# ---------------------------------------------------------------------------


def save_results(
    records: list[dict], output_dir: Path, keyword: str = "", category: str = ""
) -> Path:
    """Save search results to output directory."""
    label = keyword or category or "all"
    output_root = ensure_dir(
        output_dir / sanitize_filename(f"mee_law_{label}", "mee_law")
    )
    write_jsonl(output_root / "metadata.jsonl", records)
    write_csv(output_root / "metadata.csv", records)

    cat_counts = {}
    cat_names = {v: k for k, v in CATEGORY_MAP.items()}
    for row in records:
        c = row.get("category", "") or "未知"
        cn = cat_names.get(c, c)
        cat_counts[cn] = cat_counts.get(cn, 0) + 1

    stats = {
        "source": "mee_law",
        "keyword": keyword,
        "category": category,
        "record_count": len(records),
        "category_distribution": dict(sorted(cat_counts.items(), key=lambda x: -x[1])),
    }
    write_json(output_root / "stats_report.json", stats)

    md = render_markdown_report(
        f"生态环境部法规标准统计报告 - {label}",
        [
            (
                "概览",
                {
                    "keyword": keyword,
                    "category": category,
                    "record_count": len(records),
                },
            ),
            ("分类分布", stats["category_distribution"]),
        ],
    )
    write_text(output_root / "stats_report.md", md)
    write_json(
        output_root / "summary.json", {"source": "mee_law", "count": len(records)}
    )
    return output_root


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="生态环境部法规标准搜索/下载工具",
        epilog=(
            "Categories: 全部, 法律, 行政法规, 规章, 标准\n\n"
            "Examples:\n"
            "  python mee_law_crawler.py --search '碳' --size 20\n"
            "  python mee_law_crawler.py --category 标准 --size 50\n"
            "  python mee_law_crawler.py --category 法律 --size 100\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--search", metavar="KEYWORD", help="Search keyword in titles")
    parser.add_argument(
        "--category",
        choices=list(CATEGORY_MAP.keys()),
        default="全部",
        help="Filter by category (default: 全部)",
    )
    parser.add_argument("--size", type=int, default=20, help="Max items (default: 20)")
    parser.add_argument("--info", metavar="URL", help="Fetch detail page")
    parser.add_argument(
        "--output",
        "-o",
        default="./mee_law_output",
        help="Output directory (default: ./mee_law_output)",
    )
    parser.add_argument(
        "--rate-limit", choices=["auto", "off", "fixed", "adaptive"], default="auto"
    )
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--cache-stats", action="store_true")
    parser.add_argument("--cache-clear", action="store_true")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if BeautifulSoup is None:
        print("Error: pip install beautifulsoup4", file=sys.stderr)
        return 1

    output_dir = Path(args.output).expanduser().resolve()
    logger = setup_logger(output_dir, name="mee_law_crawler")

    if args.no_cache:
        global _cache
        _cache = _CacheManager(enabled=False, namespace="mee-law-db")
    if args.cache_stats:
        stats = _cache.stats()
        print(f"Cache: {stats['entries']} entries, {stats['size_kb']} KB")
        print(f"Location: {_cache.dir}")
        return 0
    if args.cache_clear:
        _cache.clear()
        print("Cache cleared.")
        return 0

    if args.info:
        detail = fetch_detail(args.info)
        print(json.dumps(detail, ensure_ascii=False, indent=2))
        return 0

    if not args.search and args.category == "全部":
        parser.print_help()
        return 1

    limiter, forced = init_limiter(args.rate_limit)
    limiter.init_for_task(estimated_requests=max(1, 5), forced_mode=forced)

    logger.info(
        "Start: keyword=%s, category=%s, size=%d", args.search, args.category, args.size
    )

    records = search_collect(
        keyword=args.search or "",
        category=args.category,
        max_items=args.size,
        timeout=args.timeout,
    )

    if not records:
        print("No results found.")
        return 1

    print(f"Found {len(records)} results:")
    cat_names = {v: k for k, v in CATEGORY_MAP.items()}
    for i, rec in enumerate(records, 1):
        cat_name = cat_names.get(rec.get("category", ""), rec.get("category", "?"))
        print(f"  {i}. [{cat_name}] {rec['title']}")
        if rec.get("url"):
            print(f"     链接: {rec['url']}")
        print()

    save_results(records, output_dir, keyword=args.search or "", category=args.category)
    print(f"Results saved to: {output_dir}")
    limiter.print_summary()
    logger.info("Done: %d records", len(records))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
