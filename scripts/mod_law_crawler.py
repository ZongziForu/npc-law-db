#!/usr/bin/env python3
"""
Download/search military/national defense regulations from mod.gov.cn (国防部法规文库).

Source: http://www.mod.gov.cn/gfbw/fgwx/index.html

Categories:
  法律法规(flfg), 白皮书(bps), 文件(wj_213958),
  司法解释(sfjs), 出版物(cbw), 热点聚焦(rdjj_213961), 政策解读(zcjd)

Usage:
  python mod_law_crawler.py --category 法律法规 --size 20
  python mod_law_crawler.py --search "军队" --size 50
  python mod_law_crawler.py --info "http://www.mod.gov.cn/gfbw/fgwx/flfg/16448581.html"
"""

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urljoin

from common import (
    _CacheManager,
    clean_text,
    ensure_dir,
    format_request_exception,
    DEFAULT_USER_AGENT,
    get_cache,
    http_request,
    init_limiter,
    render_markdown_report,
    sanitize_filename,
    setup_logger,
    unique_path,
    write_csv,
    write_json,
    write_jsonl,
    write_text,
)

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

BASE_URL = "http://www.mod.gov.cn"
FG_BASE = f"{BASE_URL}/gfbw/fgwx"

CATEGORY_MAP = {
    "全部": "",
    "法律法规": "flfg",
    "白皮书": "bps",
    "文件": "wj_213958",
    "司法解释": "sfjs",
    "出版物": "cbw",
    "热点聚焦": "rdjj_213961",
    "政策解读": "zcjd",
}

HEADERS = {
    "User-Agent": DEFAULT_USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

_cache = get_cache("mod-law-db")


# ---------------------------------------------------------------------------
# List page parsing
# ---------------------------------------------------------------------------


def fetch_category_index(category_path: str, timeout: int = 30):
    """Fetch a category's index page with article listing."""
    if category_path:
        url = f"{FG_BASE}/{category_path}/index.html"
    else:
        url = f"{FG_BASE}/index.html"

    cache_key = _cache._key("list", category_path or "all")
    cached = _cache.get(cache_key, max_age=3600)
    if cached:
        return cached

    resp = http_request("GET", url, headers=HEADERS, timeout=timeout)
    resp.encoding = "utf-8"
    _cache.set(cache_key, resp.text)
    return resp.text


def parse_category_page(html: str, category: str = "") -> list[dict]:
    """Parse a category listing page to extract article links."""
    records = []

    if BeautifulSoup is None:
        return records

    soup = BeautifulSoup(html, "html.parser")

    # Find article links: URLs containing /gfbw/fgwx/{category}/
    links = soup.find_all("a", href=True)
    seen_urls = set()

    for link in links:
        href = link["href"]
        text = link.get_text(" ", strip=True)

        # Must be an article page (numeric ID in URL)
        if not re.search(r"/\d+\.html$", href):
            continue

        # Must be within the fgwx section
        if "/gfbw/fgwx/" not in href:
            continue

        # Skip "显示更多" links
        if "显示更多" in text:
            continue

        if len(text) < 5:
            continue

        full_url = urljoin(BASE_URL, href)
        if full_url in seen_urls:
            continue
        seen_urls.add(full_url)

        # Determine sub-category from URL
        sub_cat = category
        if not sub_cat:
            cat_match = re.search(r"/fgwx/([^/]+)/", href)
            if cat_match:
                sub_cat = cat_match.group(1)

        records.append({
            "source": "mod_law",
            "category": sub_cat,
            "title": clean_text(text),
            "url": full_url,
        })

    return records


def fetch_full_list_page(category_path: str, timeout: int = 30) -> list[dict]:
    """Fetch a category's index page which lists all articles."""
    return parse_category_page(
        fetch_category_index(category_path, timeout=timeout),
        category=category_path,
    )


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
        "source": "",
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
            or soup.select_one(".con_text")
            or soup.select_one(".TRS_Editor")
            or soup.select_one("main")
            or soup.select_one("article")
        )
        if content_node:
            result["content_text"] = clean_text(
                content_node.get_text("\n", strip=True)
            )

        # Date
        date_node = (
            soup.select_one(".date")
            or soup.select_one(".time")
            or soup.select_one(".pub-date")
            or soup.select_one(".publish-time")
            or soup.select_one(".sj")
        )
        if date_node:
            result["publish_date"] = clean_text(
                date_node.get_text(" ", strip=True)
            )

        # Source
        source_node = (
            soup.select_one(".source")
            or soup.select_one(".origin")
            or soup.select_one(".ly")
        )
        if source_node:
            result["source"] = clean_text(
                source_node.get_text(" ", strip=True)
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


def search_collect(keyword: str = "", category: str = "",
                   max_items: int = 20, timeout: int = 30) -> list[dict]:
    """Search and collect military regulations."""
    records = []
    cat_key = CATEGORY_MAP.get(category, "")

    if cat_key:
        categories_to_fetch = [cat_key]
    else:
        categories_to_fetch = list(CATEGORY_MAP.values())[1:]  # skip "全部"

    for cat in categories_to_fetch:
        if len(records) >= max_items:
            break
        items = fetch_full_list_page(category_path=cat, timeout=timeout)

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


def save_results(records: list[dict], output_dir: Path,
                 keyword: str = "", category: str = "") -> Path:
    """Save search results to output directory."""
    label = keyword or category or "all"
    output_root = ensure_dir(
        output_dir / sanitize_filename(f"mod_law_{label}", "mod_law")
    )
    write_jsonl(output_root / "metadata.jsonl", records)
    write_csv(output_root / "metadata.csv", records)

    cat_counts = {}
    for row in records:
        c = row.get("category", "") or "未知"
        cat_counts[c] = cat_counts.get(c, 0) + 1

    stats = {
        "source": "mod_law",
        "keyword": keyword,
        "category": category,
        "record_count": len(records),
        "category_distribution": dict(sorted(cat_counts.items(), key=lambda x: -x[1])),
    }
    write_json(output_root / "stats_report.json", stats)

    md = render_markdown_report(
        f"国防部法规文库统计报告 - {label}",
        [
            ("概览", {"keyword": keyword, "category": category, "record_count": len(records)}),
            ("分类分布", stats["category_distribution"]),
        ],
    )
    write_text(output_root / "stats_report.md", md)
    write_json(output_root / "summary.json", {"source": "mod_law", "count": len(records)})
    return output_root


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="国防部法规文库搜索/下载工具 (mod.gov.cn)",
        epilog=(
            "Categories: 全部, 法律法规, 白皮书, 文件, 司法解释, 出版物, 热点聚焦, 政策解读\n\n"
            "Examples:\n"
            "  python mod_law_crawler.py --category 法律法规 --size 20\n"
            "  python mod_law_crawler.py --search '军队' --size 50\n"
            "  python mod_law_crawler.py --info 'http://www.mod.gov.cn/gfbw/fgwx/flfg/16448581.html'\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--search", metavar="KEYWORD", help="Search keyword in titles")
    parser.add_argument("--category",
                        choices=list(CATEGORY_MAP.keys()),
                        default="全部",
                        help="Filter by category (default: 全部)")
    parser.add_argument("--size", type=int, default=20, help="Max items (default: 20)")
    parser.add_argument("--info", metavar="URL", help="Fetch detail page")
    parser.add_argument("--output", "-o", default="./mod_law_output",
                        help="Output directory (default: ./mod_law_output)")
    parser.add_argument("--rate-limit", choices=["auto", "off", "fixed", "adaptive"],
                        default="auto")
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
    logger = setup_logger(output_dir, name="mod_law_crawler")

    if args.no_cache:
        global _cache
        _cache = _CacheManager(enabled=False, namespace="mod-law-db")
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
    limiter.init_for_task(estimated_requests=max(1, 7), forced_mode=forced)

    logger.info("Start: keyword=%s, category=%s, size=%d",
                args.search, args.category, args.size)

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
