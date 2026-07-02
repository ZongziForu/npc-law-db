#!/usr/bin/env python3
"""
Download/search judicial interpretations and documents from the Supreme People's Court (最高人民法院).

Source: https://www.court.gov.cn/fabu.html

Categories (栏目编号):
  司法解释(16), 司法文件(17), 重大案件(15), 通知(22), etc.

Usage:
  python court_law_crawler.py --search "建设工程" --size 20
  python court_law_crawler.py --category 司法解释 --size 50
  python court_law_crawler.py --category 司法文件 --size 30
  python court_law_crawler.py --info "https://www.court.gov.cn/fabu/xiangqing/504221.html"
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

BASE_URL = "https://www.court.gov.cn"

CATEGORY_MAP = {
    "全部": "",
    "司法解释": "16",
    "司法文件": "17",
    "重大案件": "15",
    "通知": "22",
    "司法数据": "21",
    "大数据专题": "662",
    "标准化工作": "108",
    "任免招录": "79",
    "开庭公告": "14",
}

CATEGORY_NAMES = {v: k for k, v in CATEGORY_MAP.items() if v}

HEADERS = {
    "User-Agent": DEFAULT_USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

_cache = get_cache("court-law-db")


# ---------------------------------------------------------------------------
# List page parsing
# ---------------------------------------------------------------------------


def fetch_list_page(category_id: str, page: int = 1, timeout: int = 30):
    """Fetch a category list page.

    Page 1: /fabu/gengduo/{cat_id}.html
    Page N: /fabu/gengduo/{cat_id}_{N}.html
    """
    if page == 1:
        url = f"{BASE_URL}/fabu/gengduo/{category_id}.html"
    else:
        url = f"{BASE_URL}/fabu/gengduo/{category_id}_{page}.html"

    cache_key = _cache._key("list", category_id, str(page))
    cached = _cache.get(cache_key, max_age=3600)
    if cached:
        return cached

    resp = http_request("GET", url, headers=HEADERS, timeout=timeout)
    resp.encoding = "utf-8"
    _cache.set(cache_key, resp.text)
    return resp.text


def parse_list_page(html: str) -> tuple[list[dict], int]:
    """Parse list page HTML into structured records.

    Returns:
        (list of records, total page count)
    """
    records = []
    total_pages = 0

    if BeautifulSoup is None:
        return records, total_pages

    soup = BeautifulSoup(html, "html.parser")

    # Find article links
    links = soup.find_all("a", href=True)
    seen_urls = set()

    for link in links:
        href = link["href"]
        text = link.get_text(" ", strip=True)

        if "/fabu/xiangqing/" not in href:
            continue
        if len(text) < 5:
            continue

        full_url = urljoin(BASE_URL, href)
        if full_url in seen_urls:
            continue
        seen_urls.add(full_url)

        records.append(
            {
                "source": "court_law",
                "title": clean_text(text),
                "url": full_url,
            }
        )

    # Find total page count from pagination links
    pagination = soup.find_all("a", href=re.compile(r"/fabu/gengduo/\d+_\d+"))
    for a in pagination:
        match = re.search(r"_(\d+)\.html$", a.get("href", ""))
        if match:
            p = int(match.group(1))
            if p > total_pages:
                total_pages = p

    # Also check the first page for 尾页 link
    last_link = soup.find(
        "a",
        href=re.compile(r"/fabu/gengduo/\d+_\d+\.html$"),
        string=re.compile(r"尾页"),
    )
    if last_link:
        match = re.search(r"_(\d+)\.html$", last_link.get("href", ""))
        if match:
            total_pages = max(total_pages, int(match.group(1)))

    return records, total_pages


# ---------------------------------------------------------------------------
# Detail page parsing
# ---------------------------------------------------------------------------


def fetch_detail(detail_url: str, timeout: int = 30) -> dict:
    """Fetch and parse a judicial document detail page."""
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

        # Title from h1
        h1 = soup.select_one("h1")
        if h1:
            result["title"] = clean_text(h1.get_text(" ", strip=True))

        # Content
        content = (
            soup.select_one("div.detail")
            or soup.select_one("div.txt_txt")
            or soup.select_one("div.txt big")
            or soup.select_one("div.content")
            or soup.select_one("article")
            or soup.select_one("main")
        )
        if content:
            result["content_text"] = clean_text(content.get_text("\n", strip=True))

        # Parse date and source from the detail page text
        full_text = soup.get_text("\n", strip=True)
        date_match = re.search(
            r"发布时间[：:]\s*(\d{4}-\d{2}-\d{2}\s*\d{2}:\d{2})", full_text
        )
        if date_match:
            result["publish_date"] = date_match.group(1)

        source_match = re.search(r"来源[：:]\s*([^\n]{2,30})", full_text)
        if source_match:
            result["source"] = clean_text(source_match.group(1))

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
    """Search and collect judicial documents."""
    records = []
    cat_key = CATEGORY_MAP.get(category, "")

    if cat_key:
        categories_to_fetch = [cat_key]
    else:
        # Default to司法解释 and 司法文件 for "全部"
        categories_to_fetch = ["16", "17"]

    for cat_id in categories_to_fetch:
        if len(records) >= max_items:
            break

        page = 1
        total_pages = 1

        while len(records) < max_items and page <= total_pages:
            html = fetch_list_page(cat_id, page=page, timeout=timeout)
            items, total_pages = parse_list_page(html)

            if not items:
                break

            if keyword:
                items = search_keyword_in_records(items, keyword)

            for item in items:
                if len(records) >= max_items:
                    break
                item["category"] = CATEGORY_NAMES.get(cat_id, f"栏目{cat_id}")
                records.append(item)

            page += 1

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
        output_dir / sanitize_filename(f"court_law_{label}", "court_law")
    )
    write_jsonl(output_root / "metadata.jsonl", records)
    write_csv(output_root / "metadata.csv", records)

    cat_counts = {}
    for row in records:
        c = row.get("category", "") or "未知"
        cat_counts[c] = cat_counts.get(c, 0) + 1

    stats = {
        "source": "court_law",
        "keyword": keyword,
        "category": category,
        "record_count": len(records),
        "category_distribution": dict(sorted(cat_counts.items(), key=lambda x: -x[1])),
    }
    write_json(output_root / "stats_report.json", stats)

    md = render_markdown_report(
        f"最高人民法院发布栏目统计报告 - {label}",
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
        output_root / "summary.json", {"source": "court_law", "count": len(records)}
    )
    return output_root


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="最高人民法院发布栏目搜索/下载工具",
        epilog=(
            "Categories: 全部(司法解释+司法文件), 司法解释, 司法文件, 重大案件, 通知, 司法数据, 大数据专题, 标准化工作, 任免招录, 开庭公告\n\n"
            "Examples:\n"
            "  python court_law_crawler.py --search '建设工程' --size 20\n"
            "  python court_law_crawler.py --category 司法解释 --size 50\n"
            "  python court_law_crawler.py --category 司法文件 --size 30\n"
            "  python court_law_crawler.py --info 'https://www.court.gov.cn/fabu/xiangqing/504221.html'\n"
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
        default="./court_law_output",
        help="Output directory (default: ./court_law_output)",
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
    logger = setup_logger(output_dir, name="court_law_crawler")

    if args.no_cache:
        global _cache
        _cache = _CacheManager(enabled=False, namespace="court-law-db")
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
    limiter.init_for_task(
        estimated_requests=max(1, args.size // 20 + 5), forced_mode=forced
    )

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
