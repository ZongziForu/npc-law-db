#!/usr/bin/env python3
"""
Download/search policies from the State Council Policy Document Library (国务院政策文件库).

Source: https://sousuo.www.gov.cn/zcwjk/policyDocumentLibrary
API:    GET /search-gov/data

Usage:
  python gov_policy_library.py --search "营商环境" --size 20
  python gov_policy_library.py --search "营商环境" --range content --size 50
  python gov_policy_library.py --search "营商环境" --category 国务院文件 --size 100
  python gov_policy_library.py --info "https://www.gov.cn/gongbao/content/2024/content_12345.htm"
  python gov_policy_library.py --search "放管服" --year 2024 --size 50
"""

import argparse
import json
import re
from pathlib import Path

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

BASE_URL = "https://sousuo.www.gov.cn"
SEARCH_API = "/search-gov/data"
HEADERS = {
    "User-Agent": DEFAULT_USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Category filter mapping (from the page UI)
CATEGORY_MAP = {
    "全部": "",
    "国务院文件": "gongwen",
    "国务院部门文件": "bumenfile",
    "解读": "otherfile",
}

SORT_MAP = {
    "score": "score",
    "time": "pubtime",
}

_cache = get_cache("gov-policy-lib")


# ---------------------------------------------------------------------------
# Search API
# ---------------------------------------------------------------------------


def search_policies(
    keyword: str,
    page: int = 0,
    size: int = 10,
    search_field: str = "title",
    sort: str = "score",
    topic: str = "zhengcelibrary",
    category: str = "",
    year: str = "",
    department: str = "",
    timeout: int = 30,
) -> dict:
    """Search the State Council Policy Document Library.

    Args:
        keyword: Search query
        page: Page number (0-based)
        size: Results per page (default 10)
        search_field: 'title' or 'content'
        sort: 'score' or 'pubtime'
        topic: Search topic (default 'zhengcelibrary')
        category: Document category filter
        year: Filter by publication year (e.g., '2024')
        department: Filter by department name
    """
    cache_key = _cache._key(
        "search",
        keyword,
        str(page),
        str(size),
        search_field,
        sort,
        topic,
        category,
        year,
        department,
    )
    cached = _cache.get(cache_key, max_age=1800)
    if cached:
        return cached

    params = {
        "t": topic,
        "q": keyword,
        "searchfield": search_field,
        "sort": sort,
        "sortType": 1,
        "p": page,
        "n": size,
        "type": "gwyzcwjk",
    }
    if category:
        params["childtype"] = category
    if year:
        params["pubtimeyear"] = year
    if department:
        params["bmfl"] = department

    resp = http_request(
        "GET",
        f"{BASE_URL}{SEARCH_API}",
        params=params,
        headers=HEADERS,
        timeout=timeout,
    )
    data = resp.json()
    _cache.set(cache_key, data)
    return data


def parse_search_results(data: dict) -> list[dict]:
    """Extract search results from API response."""
    results = []
    if data.get("code") != 200:
        return results

    search_vo = data.get("searchVO", {})
    cat_map = search_vo.get("catMap", {})

    for cat_name, cat_data in cat_map.items():
        items = cat_data.get("listVO", [])
        for item in items:
            title = clean_text(item.get("title", ""))
            if not title:
                continue
            results.append(
                {
                    "source": "gov_policy_library",
                    "category": cat_name,
                    "title": title,
                    "url": item.get("piclinksurl", ""),
                    "code": item.get("code", ""),
                    "pcode": item.get("pcode", ""),
                    "pub_time": clean_text(item.get("pubtime", "")),
                    "summary": clean_text(item.get("summary", "")),
                    "content": clean_text(item.get("content", "")),
                    "department": clean_text(item.get("source", "")),
                }
            )

    return results


def get_facet_info(data: dict) -> dict:
    """Extract facet/filter information from search response."""
    search_vo = data.get("searchVO", {})
    extend = search_vo.get("extendresult", {})
    return {
        "group_map": extend.get("groupMap", {}),
        "facet_map": extend.get("facetMap", {}),
        "total_count": search_vo.get("totalCount", 0),
    }


# ---------------------------------------------------------------------------
# Detail page parsing (for --info flag)
# ---------------------------------------------------------------------------


def fetch_detail_page(url: str, timeout: int = 30) -> dict:
    """Fetch and parse a policy detail page."""
    cache_key = _cache._key("detail", url)
    cached = _cache.get(cache_key, max_age=86400)
    if cached:
        return cached

    resp = http_request("GET", url, headers=HEADERS, timeout=timeout)
    resp.encoding = "utf-8"

    result = {
        "url": url,
        "title": "",
        "content_text": "",
        "publish_date": "",
        "source": "",
    }

    if BeautifulSoup is not None:
        soup = BeautifulSoup(resp.text, "html.parser")

        # Try common title selectors
        title_node = (
            soup.select_one("h1")
            or soup.select_one(".article-title")
            or soup.select_one(".title")
            or soup.select_one("h2")
        )
        if title_node:
            result["title"] = clean_text(title_node.get_text(" ", strip=True))

        # Try content selectors
        content_node = (
            soup.select_one(".article-content")
            or soup.select_one(".content")
            or soup.select_one("#content")
            or soup.select_one(".pages_content")
        )
        if content_node:
            result["content_text"] = clean_text(content_node.get_text("\n", strip=True))

        # Try date
        date_node = soup.select_one(".date, .time, .pub-date, .publish-time")
        if date_node:
            result["publish_date"] = clean_text(date_node.get_text(" ", strip=True))

        # Try source
        source_node = soup.select_one(".source, .origin")
        if source_node:
            result["source"] = clean_text(source_node.get_text(" ", strip=True))

    _cache.set(cache_key, result)
    return result


# ---------------------------------------------------------------------------
# Search and collect
# ---------------------------------------------------------------------------


def search_collect(
    keyword: str,
    max_items: int = 20,
    search_field: str = "title",
    sort: str = "score",
    topic: str = "zhengcelibrary",
    category: str = "",
    year: str = "",
    department: str = "",
    timeout: int = 30,
) -> list[dict]:
    """Search and collect results across paginated results."""
    records = []
    page = 0
    page_size = min(max_items, 50)  # Fetch up to 50 per page

    while len(records) < max_items:
        data = search_policies(
            keyword,
            page=page,
            size=page_size,
            search_field=search_field,
            sort=sort,
            topic=topic,
            category=category,
            year=year,
            department=department,
            timeout=timeout,
        )
        items = parse_search_results(data)
        if not items:
            break

        for item in items:
            if len(records) >= max_items:
                break
            records.append(item)

        # Check if there are more pages
        search_vo = data.get("searchVO", {})
        total = search_vo.get("totalCount", 0)
        if (page + 1) * page_size >= total:
            break
        page += 1

    return records


# ---------------------------------------------------------------------------
# Output / report
# ---------------------------------------------------------------------------


def save_results(records: list[dict], output_dir: Path, keyword: str = "") -> Path:
    """Save search results to output directory."""
    output_root = ensure_dir(
        output_dir / sanitize_filename(f"gov_policy_{keyword or 'all'}", "gov_policy")
    )
    write_jsonl(output_root / "metadata.jsonl", records)
    write_csv(output_root / "metadata.csv", records)

    # Generate stats
    dept_counts = {}
    cat_counts = {}
    year_counts = {}
    for row in records:
        dept = row.get("department", "") or "未知"
        dept_counts[dept] = dept_counts.get(dept, 0) + 1
        cat = row.get("category", "") or "未知"
        cat_counts[cat] = cat_counts.get(cat, 0) + 1
        pub_time = row.get("pub_time", "")
        year_match = re.search(r"(\d{4})", pub_time)
        if year_match:
            y = year_match.group(1)
            year_counts[y] = year_counts.get(y, 0) + 1

    stats = {
        "source": "gov_policy_library",
        "keyword": keyword,
        "record_count": len(records),
        "department_distribution": dict(
            sorted(dept_counts.items(), key=lambda x: -x[1])
        ),
        "category_distribution": dict(sorted(cat_counts.items(), key=lambda x: -x[1])),
        "year_distribution": dict(sorted(year_counts.items())),
    }
    write_json(output_root / "stats_report.json", stats)

    md = render_markdown_report(
        f"国务院政策文件库统计报告 - {keyword or '全部'}",
        [
            ("概览", {"keyword": keyword, "record_count": len(records)}),
            ("发文机关分布", stats["department_distribution"]),
            ("分类分布", stats["category_distribution"]),
            ("发布年份分布", stats["year_distribution"]),
        ],
    )
    write_text(output_root / "stats_report.md", md)
    write_json(
        output_root / "summary.json",
        {"source": "gov_policy_library", "count": len(records)},
    )
    return output_root


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="国务院政策文件库搜索/下载工具",
        epilog=(
            "Examples:\n"
            "  python gov_policy_library.py --search '营商环境'\n"
            "  python gov_policy_library.py --search '放管服' --range content --size 50\n"
            "  python gov_policy_library.py --search '国务院' --category 国务院文件 --size 100\n"
            "  python gov_policy_library.py --info 'https://www.gov.cn/gongbao/content/xxx.htm'\n"
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
    parser.add_argument("--info", metavar="URL", help="Fetch detail page")
    parser.add_argument("--size", type=int, default=20, help="Max items (default: 20)")
    parser.add_argument(
        "--sort",
        choices=["score", "time"],
        default="score",
        help="Sort by score or time (default: score)",
    )
    parser.add_argument(
        "--category",
        choices=["全部", "国务院文件", "国务院部门文件", "解读"],
        default="",
        help="Filter by document category",
    )
    parser.add_argument("--year", help="Filter by publication year (e.g., 2024)")
    parser.add_argument("--department", help="Filter by department name")
    parser.add_argument(
        "--output",
        "-o",
        default="./gov_policy_output",
        help="Output directory (default: ./gov_policy_output)",
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

    output_dir = Path(args.output).expanduser().resolve()
    logger = setup_logger(output_dir, name="gov_policy_library")

    if args.no_cache:
        global _cache
        _cache = _CacheManager(enabled=False, namespace="gov-policy-lib")
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
        detail = fetch_detail_page(args.info)
        print(json.dumps(detail, ensure_ascii=False, indent=2))
        return 0

    if not args.search:
        parser.print_help()
        return 1

    limiter, forced = init_limiter(args.rate_limit)
    limiter.init_for_task(
        estimated_requests=max(1, args.size // 50 + 1), forced_mode=forced
    )

    search_field = "content" if args.range == "content" else "title"
    cat_key = CATEGORY_MAP.get(args.category, "")

    logger.info(
        "Start: keyword=%s, field=%s, category=%s, size=%d",
        args.search,
        search_field,
        args.category,
        args.size,
    )

    records = search_collect(
        keyword=args.search,
        max_items=args.size,
        search_field=search_field,
        sort=args.sort,
        category=cat_key,
        year=args.year or "",
        department=args.department or "",
        timeout=args.timeout,
    )

    if not records:
        print("No results found.")
        return 1

    # Print summary
    print(f"Found {len(records)} results:")
    for i, rec in enumerate(records, 1):
        print(f"  {i}. {rec['title']}")
        if rec.get("pcode"):
            print(f"     文号: {rec['pcode']}")
        if rec.get("department"):
            print(f"     发文机关: {rec['department']}")
        if rec.get("pub_time"):
            print(f"     时间: {rec['pub_time']}")
        if rec.get("url"):
            print(f"     链接: {rec['url']}")
        print()

    # Save
    save_results(records, output_dir, keyword=args.search)
    print(f"Results saved to: {output_dir}")
    limiter.print_summary()
    logger.info("Done: %d records", len(records))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
