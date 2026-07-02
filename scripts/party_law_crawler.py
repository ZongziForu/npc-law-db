#!/usr/bin/env python3
"""
Download/search internal Party regulations from 12371.cn (共产党员网 - 党内法规).

Source: https://www.12371.cn/special/dnfg/

Categories:
  党章(zz), 条例(tl), 规定(gd), 办法(bf), 规则(gz), 细则(xz)
  党章 党章, 党的组织法规(zzfg), 党的领导法规(ldfg),
  党的自身建设法规(zsjs), 党的监督保障法规(jdbz)

Usage:
  python party_law_crawler.py --search "纪律" --size 20
  python party_law_crawler.py --category 条例 --size 50
  python party_law_crawler.py --info "https://www.12371.cn/2022/01/23/ARTI1642937162249109.shtml"
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

BASE_URL = "https://www.12371.cn"
BASE_PATH = "/special/dnfg"

CATEGORY_MAP = {
    "全部": "",
    "党章": "zz",
    "条例": "tl",
    "规定": "gd",
    "办法": "bf",
    "规则": "gz",
    "细则": "xz",
    "党的组织法规": "zzfg",
    "党的领导法规": "ldfg",
    "党的自身建设法规": "zsjs",
    "党的监督保障法规": "jdbz",
}

HEADERS = {
    "User-Agent": DEFAULT_USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

_cache = get_cache("party-law-db")


# ---------------------------------------------------------------------------
# Category list page parsing
# ---------------------------------------------------------------------------


def fetch_category_page(category: str = "", page: int = 1, timeout: int = 30):
    """Fetch a category listing page from 12371.cn party law section."""
    if category:
        url = f"{BASE_URL}{BASE_PATH}/{category}/"
    else:
        url = f"{BASE_URL}{BASE_PATH}/"

    cache_key = _cache._key("list", category or "all", str(page))
    cached = _cache.get(cache_key, max_age=3600)
    if cached:
        return cached

    resp = http_request("GET", url, headers=HEADERS, timeout=timeout)
    resp.encoding = "utf-8"
    _cache.set(cache_key, resp.text)
    return resp.text


def parse_category_page(html: str) -> list[dict]:
    """Parse category listing page to extract regulation links."""
    records = []

    if BeautifulSoup is None:
        return records

    soup = BeautifulSoup(html, "html.parser")

    # Find article links. 12371.cn uses various layouts.
    # Common patterns: links in list items, article cards
    links = soup.find_all("a", href=True)

    seen_urls = set()
    for link in links:
        href = link["href"]
        text = link.get_text(" ", strip=True)

        # Filter for article links (detailed content pages)
        # 12371.cn article URLs look like:
        # /2022/01/23/ARTI1642937162249109.shtml
        if not re.search(r"/\d{4}/\d{2}/\d{2}/", href):
            continue
        if not href.endswith(".shtml"):
            continue
        if len(text) < 5:
            continue

        full_url = urljoin(BASE_URL, href)
        if full_url in seen_urls:
            continue
        seen_urls.add(full_url)

        records.append(
            {
                "source": "party_law",
                "title": clean_text(text),
                "url": full_url,
            }
        )

    return records


# ---------------------------------------------------------------------------
# Detail page parsing
# ---------------------------------------------------------------------------


def fetch_detail(detail_url: str, timeout: int = 30) -> dict:
    """Fetch and parse a party regulation detail page."""
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
        "full_html": resp.text,
    }

    if BeautifulSoup is not None:
        soup = BeautifulSoup(resp.text, "html.parser")

        # Title
        title_node = (
            soup.select_one("h1")
            or soup.select_one(".article-title")
            or soup.select_one(".title")
            or soup.select_one("h2")
            or soup.select_one(".bt")
        )
        if title_node:
            result["title"] = clean_text(title_node.get_text(" ", strip=True))

        # Content
        content_node = (
            soup.select_one(".article-content")
            or soup.select_one(".content")
            or soup.select_one("#content")
            or soup.select_one(".pages_content")
            or soup.select_one(".TRS_Editor")
            or soup.select_one(".con_text")
            or soup.select_one("main")
        )
        if content_node:
            result["content_text"] = clean_text(content_node.get_text("\n", strip=True))

        # Date
        date_node = (
            soup.select_one(".date")
            or soup.select_one(".time")
            or soup.select_one(".pub-date")
            or soup.select_one(".sj")
        )
        if date_node:
            result["publish_date"] = clean_text(date_node.get_text(" ", strip=True))

        # Also try to find date in the URL path (/2022/01/23/)
        if not result["publish_date"]:
            date_match = re.search(r"/(\d{4})/(\d{2})/(\d{2})/", detail_url)
            if date_match:
                result["publish_date"] = (
                    f"{date_match.group(1)}-{date_match.group(2)}-{date_match.group(3)}"
                )

    _cache.set(cache_key, result)
    return result


# ---------------------------------------------------------------------------
# Search and collect
# ---------------------------------------------------------------------------


def search_keyword_in_text(records: list[dict], keyword: str) -> list[dict]:
    """Filter records whose title matches the keyword (server-side)."""
    if not keyword:
        return records
    kw = keyword.lower()
    return [r for r in records if kw in r["title"].lower()]


def search_collect(
    keyword: str = "", category: str = "", max_items: int = 20, timeout: int = 30
) -> list[dict]:
    """Search and collect party regulations."""
    records = []
    cat_key = CATEGORY_MAP.get(category, "")
    categories_to_fetch = [cat_key] if cat_key else list(CATEGORY_MAP.values())[1:]

    for cat in categories_to_fetch:
        if len(records) >= max_items:
            break
        html = fetch_category_page(category=cat, timeout=timeout)
        items = parse_category_page(html)

        # Filter by keyword if provided
        if keyword:
            items = search_keyword_in_text(items, keyword)

        for item in items:
            if len(records) >= max_items:
                break
            item["category"] = cat
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
        output_dir / sanitize_filename(f"party_law_{label}", "party_law")
    )
    write_jsonl(output_root / "metadata.jsonl", records)
    write_csv(output_root / "metadata.csv", records)

    cat_counts = {}
    for row in records:
        c = row.get("category", "") or "未知"
        cat_counts[c] = cat_counts.get(c, 0) + 1

    stats = {
        "source": "party_law",
        "keyword": keyword,
        "category": category,
        "record_count": len(records),
        "category_distribution": dict(sorted(cat_counts.items(), key=lambda x: -x[1])),
    }
    write_json(output_root / "stats_report.json", stats)

    md = render_markdown_report(
        f"党内法规库统计报告 - {keyword or category or '全部'}",
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
        output_root / "summary.json", {"source": "party_law", "count": len(records)}
    )
    return output_root


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="党内法规库搜索/下载工具 (12371.cn)",
        epilog=(
            "Categories: 全部, 党章, 条例, 规定, 办法, 规则, 细则, "
            "党的组织法规, 党的领导法规, 党的自身建设法规, 党的监督保障法规\n\n"
            "Examples:\n"
            "  python party_law_crawler.py --search '纪律'\n"
            "  python party_law_crawler.py --category 条例 --size 50\n"
            "  python party_law_crawler.py --info 'https://www.12371.cn/2022/01/23/ARTI...shtml'\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--search", metavar="KEYWORD", help="Search keyword")
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
        default="./party_law_output",
        help="Output directory (default: ./party_law_output)",
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
    logger = setup_logger(output_dir, name="party_law_crawler")

    if args.no_cache:
        global _cache
        _cache = _CacheManager(enabled=False, namespace="party-law-db")
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
    for i, rec in enumerate(records, 1):
        print(f"  {i}. [{rec.get('category', '?')}] {rec['title']}")
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
