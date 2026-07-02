#!/usr/bin/env python3
"""
Download/search administrative regulations from the Ministry of Justice (司法部行政法规库).

Source: https://xzfg.moj.gov.cn/search2.html

This is a server-side rendered HTML site. Search is done via URL parameters.

Usage:
  python moj_law_crawler.py --search "营商环境" --size 20
  python moj_law_crawler.py --search "行政复议" --range content --size 50
  python moj_law_crawler.py --search "行政处罚" --status effective --size 100
  python moj_law_crawler.py --info "https://xzfg.moj.gov.cn/detail?xxx"
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

BASE_URL = "https://xzfg.moj.gov.cn"
SEARCH_URL = f"{BASE_URL}/search2.html"
HEADERS = {
    "User-Agent": DEFAULT_USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

STATUS_MAP = {
    "all": "",
    "effective": "1",
    "invalid": "2",
}

RANGE_MAP = {
    "title": "1",
    "content": "2",
}

_cache = get_cache("moj-law-db")


# ---------------------------------------------------------------------------
# Search page parsing
# ---------------------------------------------------------------------------


def fetch_search_page(
    keyword: str,
    page: int = 1,
    page_size: int = 10,
    search_range: str = "title",
    status: str = "all",
    timeout: int = 30,
):
    """Fetch search results page from the MoJ law database."""
    cache_key = _cache._key("search", keyword, str(page), search_range, status)
    cached = _cache.get(cache_key, max_age=1800)
    if cached:
        return cached

    params = {
        "SearchWord": keyword,
        "pageIndex": page,
        "pageSize": page_size,
        "searchField": RANGE_MAP.get(search_range, "1"),
    }
    if status and status != "all":
        params["effect"] = STATUS_MAP.get(status, "")

    resp = http_request(
        "GET", SEARCH_URL, params=params, headers=HEADERS, timeout=timeout
    )
    resp.encoding = "utf-8"
    _cache.set(cache_key, resp.text)
    return resp.text


def parse_search_results(html: str) -> tuple[list[dict], int]:
    """Parse search results HTML into structured records.

    Returns:
        (list of records, total page count)
    """
    records = []
    total_pages = 0

    if BeautifulSoup is None:
        return records, total_pages

    soup = BeautifulSoup(html, "html.parser")

    # Get total page count
    page_count_input = soup.select_one("#page-count")
    if page_count_input:
        try:
            total_pages = int(page_count_input.get("value", 0))
        except (ValueError, TypeError):
            total_pages = 0

    # Find result items
    # The page uses <li> elements with class not easily identifiable
    # Look for the result list container
    result_items = soup.select(
        ".searching-results-list .list-item, "
        ".list-item, "
        "ul > li.list-item, "
        "div.list-item"
    )

    # Fallback: find items by looking for a pattern of links
    if not result_items:
        # Try to find the main result area
        main_area = soup.select_one(
            ".searching-results-list, .results-list, main, .main-content, .content"
        )
        if main_area:
            result_items = main_area.find_all("div", class_=re.compile(r"item", re.I))
            if not result_items:
                result_items = main_area.find_all("li")

    for item in result_items:
        text = item.get_text("\n", strip=True)
        if not text or len(text) < 10:
            continue

        # Find title link
        link = item.find("a") if item.find("a") else None
        title = clean_text(link.get_text(" ", strip=True)) if link else ""
        detail_url = ""
        if link and link.get("href"):
            detail_url = urljoin(BASE_URL, link["href"])

        if not title:
            # Try to extract title from first strong/b element
            strong = item.find(["strong", "b"])
            if strong:
                title = clean_text(strong.get_text(" ", strip=True))
            else:
                lines = [l.strip() for l in text.split("\n") if l.strip()]
                title = lines[0] if lines else ""

        if not title:
            continue

        # Parse dates and metadata
        pub_date = ""
        eff_date = ""
        status_text = ""

        date_matches = re.findall(r"(\d{4}-\d{2}-\d{2})", text)
        if date_matches:
            # Usually the first date is publish date, second is effective date
            if "公布" in text:
                pub_match = re.search(r"(\d{4}-\d{2}-\d{2})公布", text)
                if pub_match:
                    pub_date = pub_match.group(1)
                eff_match = re.search(r"(\d{4}-\d{2}-\d{2})施行", text)
                if eff_match:
                    eff_date = eff_match.group(1)
            else:
                pub_date = date_matches[0]
                if len(date_matches) > 1:
                    eff_date = date_matches[1]

        if "现行有效" in text:
            status_text = "现行有效"
        elif "已修改" in text:
            status_text = "已修改"

        records.append(
            {
                "source": "moj_law",
                "title": title,
                "detail_url": detail_url,
                "publish_date": pub_date,
                "effective_date": eff_date,
                "status": status_text,
                "raw_text_snippet": text[:200],
            }
        )

    return records, total_pages


# ---------------------------------------------------------------------------
# Detail page parsing
# ---------------------------------------------------------------------------


def fetch_detail(detail_url: str, timeout: int = 30) -> dict:
    """Fetch and parse a regulation detail page."""
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
        "full_html": resp.text,
    }

    if BeautifulSoup is not None:
        soup = BeautifulSoup(resp.text, "html.parser")
        title_node = (
            soup.select_one("h1")
            or soup.select_one(".article-title")
            or soup.select_one(".title")
            or soup.select_one("h2")
        )
        if title_node:
            result["title"] = clean_text(title_node.get_text(" ", strip=True))

        content_node = (
            soup.select_one(".article-content")
            or soup.select_one(".content")
            or soup.select_one("#content")
            or soup.select_one(".pages_content")
            or soup.select_one("main")
        )
        if content_node:
            result["content_text"] = clean_text(content_node.get_text("\n", strip=True))

    _cache.set(cache_key, result)
    return result


# ---------------------------------------------------------------------------
# Search and collect
# ---------------------------------------------------------------------------


def search_collect(
    keyword: str,
    max_items: int = 20,
    search_range: str = "title",
    status: str = "all",
    timeout: int = 30,
) -> list[dict]:
    """Search and collect results across paginated pages."""
    records = []
    page = 1
    page_size = min(max_items, 10)
    total_pages = 1

    while len(records) < max_items and page <= total_pages:
        html = fetch_search_page(
            keyword,
            page=page,
            page_size=page_size,
            search_range=search_range,
            status=status,
            timeout=timeout,
        )
        items, total_pages = parse_search_results(html)

        if not items:
            break

        for item in items:
            if len(records) >= max_items:
                break
            records.append(item)

        page += 1

    return records


# ---------------------------------------------------------------------------
# Output / report
# ---------------------------------------------------------------------------


def save_results(records: list[dict], output_dir: Path, keyword: str = "") -> Path:
    """Save search results to output directory."""
    output_root = ensure_dir(
        output_dir / sanitize_filename(f"moj_law_{keyword or 'all'}", "moj_law")
    )
    write_jsonl(output_root / "metadata.jsonl", records)
    write_csv(output_root / "metadata.csv", records)

    status_counts = {}
    for row in records:
        s = row.get("status", "") or "未知"
        status_counts[s] = status_counts.get(s, 0) + 1

    stats = {
        "source": "moj_law",
        "keyword": keyword,
        "record_count": len(records),
        "status_distribution": dict(sorted(status_counts.items(), key=lambda x: -x[1])),
    }
    write_json(output_root / "stats_report.json", stats)

    md = render_markdown_report(
        f"司法部行政法规库统计报告 - {keyword or '全部'}",
        [
            ("概览", {"keyword": keyword, "record_count": len(records)}),
            ("时效性分布", stats["status_distribution"]),
        ],
    )
    write_text(output_root / "stats_report.md", md)
    write_json(
        output_root / "summary.json", {"source": "moj_law", "count": len(records)}
    )
    return output_root


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="司法部行政法规库搜索/下载工具",
        epilog=(
            "Examples:\n"
            "  python moj_law_crawler.py --search '营商环境'\n"
            "  python moj_law_crawler.py --search '行政复议' --range content\n"
            "  python moj_law_crawler.py --search '行政处罚' --status effective --size 50\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--search", metavar="KEYWORD", help="Search keyword")
    parser.add_argument(
        "--range",
        choices=["title", "content"],
        default="title",
        help="Search range: title (default) or content",
    )
    parser.add_argument(
        "--status",
        choices=["all", "effective", "invalid"],
        default="all",
        help="Filter by effectiveness status",
    )
    parser.add_argument("--size", type=int, default=20, help="Max items (default: 20)")
    parser.add_argument("--info", metavar="URL", help="Fetch detail page")
    parser.add_argument(
        "--output",
        "-o",
        default="./moj_law_output",
        help="Output directory (default: ./moj_law_output)",
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
    logger = setup_logger(output_dir, name="moj_law_crawler")

    if args.no_cache:
        global _cache
        _cache = _CacheManager(enabled=False, namespace="moj-law-db")
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

    if not args.search:
        parser.print_help()
        return 1

    limiter, forced = init_limiter(args.rate_limit)
    limiter.init_for_task(
        estimated_requests=max(1, args.size // 10 + 1), forced_mode=forced
    )

    logger.info(
        "Start: keyword=%s, range=%s, status=%s, size=%d",
        args.search,
        args.range,
        args.status,
        args.size,
    )

    records = search_collect(
        keyword=args.search,
        max_items=args.size,
        search_range=args.range,
        status=args.status,
        timeout=args.timeout,
    )

    if not records:
        print("No results found.")
        return 1

    print(f"Found {len(records)} results:")
    for i, rec in enumerate(records, 1):
        print(f"  {i}. {rec['title']}")
        if rec.get("publish_date"):
            print(f"     公布日期: {rec['publish_date']}")
        if rec.get("effective_date"):
            print(f"     施行日期: {rec['effective_date']}")
        if rec.get("status"):
            print(f"     状态: {rec['status']}")
        if rec.get("detail_url"):
            print(f"     链接: {rec['detail_url']}")
        print()

    save_results(records, output_dir, keyword=args.search)
    print(f"Results saved to: {output_dir}")
    limiter.print_summary()
    logger.info("Done: %d records", len(records))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
