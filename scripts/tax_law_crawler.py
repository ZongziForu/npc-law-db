#!/usr/bin/env python3
"""
Download/search tax regulations from the State Taxation Administration (国家税务总局政策法规库).

Source: https://fgk.chinatax.gov.cn/
API:    POST https://www.chinatax.gov.cn/getFileListByCodeId

Categories:
  法律(c100009), 行政法规(c100010), 国务院文件(c102440),
  税务部门规章(c100011), 财税文件(c102416), 税务规范性文件(c100012),
  其他文件(c100013), 工作通知(c102424)

Usage:
  python tax_law_crawler.py --search "增值税" --size 20
  python tax_law_crawler.py --category 财税文件 --size 50
  python tax_law_crawler.py --category 法律 --size 100
  python tax_law_crawler.py --info "https://fgk.chinatax.gov.cn/zcfgk/c102416/c5250687/content.html"
"""

import argparse
import json
import re
from pathlib import Path
from urllib.parse import urljoin

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

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

BASE_URL = "https://fgk.chinatax.gov.cn"
API_URL = "https://www.chinatax.gov.cn/getFileListByCodeId"

CATEGORY_MAP = {
    "全部": "",
    "法律": "c100009",
    "行政法规": "c100010",
    "国务院文件": "c102440",
    "税务部门规章": "c100011",
    "财税文件": "c102416",
    "税务规范性文件": "c100012",
    "其他文件": "c100013",
    "工作通知": "c102424",
}

HEADERS = {
    "User-Agent": DEFAULT_USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

CHANNEL_ID_CACHE = {}  # codeName -> channelId

_cache = get_cache("tax-law-db")


# ---------------------------------------------------------------------------
# Channel ID discovery
# ---------------------------------------------------------------------------


def discover_channel_id(session, code_name: str) -> str:
    """Visit a category page to extract the channelId from the page source."""
    cached = CHANNEL_ID_CACHE.get(code_name)
    if cached:
        return cached

    # The list pages might have different names
    possible_paths = [
        f"/zcfgk/{code_name}/listflfg.html",
        f"/zcfgk/{code_name}/listflfg_fg.html",
        f"/zcfgk/{code_name}/list_guizhang.html",
    ]

    for path in possible_paths:
        url = f"{BASE_URL}{path}"
        try:
            resp = session.get(url, headers=HEADERS, timeout=15)
            resp.encoding = "utf-8"
            match = re.search(r'channelId\s*=\s*["\']([^"\']+)["\']', resp.text)
            if match:
                channel_id = match.group(1)
                CHANNEL_ID_CACHE[code_name] = channel_id
                return channel_id
        except Exception:
            continue

    # Fallback: use the main page
    try:
        resp = session.get(f"{BASE_URL}/", headers=HEADERS, timeout=15)
        resp.encoding = "utf-8"
        match = re.search(r'channelId\s*=\s*["\']([^"\']+)["\']', resp.text)
        if match:
            channel_id = match.group(1)
            CHANNEL_ID_CACHE[code_name] = channel_id
            return channel_id
    except Exception:
        pass

    raise RuntimeError(f"Cannot discover channelId for {code_name}")


# ---------------------------------------------------------------------------
# API calls
# ---------------------------------------------------------------------------


def create_session():
    """Create a requests Session and initialize it with the main page."""
    session = requests.Session()
    session.headers.update(HEADERS)
    session.verify = False

    # Initialize session by visiting the main page
    session.get(f"{BASE_URL}/", timeout=15)
    return session


def fetch_category(
    session, code_name: str, page: int = 1, size: int = 10, timeout: int = 30
) -> dict:
    """Fetch documents from a category via the API."""
    cache_key = _cache._key("list", code_name, str(page), str(size))
    cached = _cache.get(cache_key, max_age=1800)
    if cached:
        return cached

    channel_id = discover_channel_id(session, code_name)

    payload = {
        "codeId": code_name,
        "channelId": channel_id,
        "page": page,
        "size": size,
        "sort": [],
        "relateSubChannels": False,
    }

    resp = session.post(
        API_URL,
        json=payload,
        headers={
            "Content-Type": "application/json",
            "Referer": f"{BASE_URL}/zcfgk/{code_name}/listflfg.html",
        },
        timeout=timeout,
    )
    data = resp.json()
    _cache.set(cache_key, data)
    return data


def parse_results(data: dict) -> list[dict]:
    """Parse API response into structured records."""
    records = []
    results_data = data.get("results", {}).get("data", {})
    items = results_data.get("results", [])

    for item in items:
        title = clean_text(item.get("titleHtml", ""))
        if not title:
            continue

        # Extract metadata from domainMetaList
        metadata = {}
        for meta_group in item.get("domainMetaList", []):
            group_name = meta_group.get("domainMetadataName", "")
            for entry in meta_group.get("resultList", []):
                key = entry.get("key", "")
                value = entry.get("value", "")
                if key and value:
                    metadata[key] = value

        # Build URL
        url = item.get("url", "")
        if url and not url.startswith("http"):
            url = urljoin("http://www.chinatax.gov.cn", url)

        records.append(
            {
                "source": "tax_law",
                "title": title,
                "sub_title": clean_text(item.get("subTitleHtml", "")),
                "url": url,
                "publish_time": item.get("publishedTimeStr", ""),
                "document_number": metadata.get("fz", metadata.get("writeno", "")),
                "issuer": metadata.get("issuerDepartment", metadata.get("source", "")),
                "effective_date": metadata.get("effectivedate", ""),
            }
        )

    return records


def get_total_count(data: dict) -> int:
    """Extract total count from API response."""
    return data.get("results", {}).get("data", {}).get("total", 0)


# ---------------------------------------------------------------------------
# Detail page parsing
# ---------------------------------------------------------------------------


def fetch_detail(detail_url: str, timeout: int = 30) -> dict:
    """Fetch and parse a tax regulation detail page."""
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
    return [
        r
        for r in records
        if kw in r["title"].lower()
        or kw in r.get("sub_title", "").lower()
        or kw in r.get("document_number", "").lower()
    ]


def search_collect(
    session,
    keyword: str = "",
    category: str = "",
    max_items: int = 20,
    timeout: int = 30,
) -> list[dict]:
    """Search and collect tax regulations."""
    records = []
    cat_key = CATEGORY_MAP.get(category, "")

    if cat_key:
        categories_to_fetch = [cat_key]
    else:
        categories_to_fetch = [v for v in CATEGORY_MAP.values() if v]

    for code_name in categories_to_fetch:
        if len(records) >= max_items:
            break

        page = 1
        page_size = min(max_items, 20)

        while len(records) < max_items:
            data = fetch_category(
                session, code_name, page=page, size=page_size, timeout=timeout
            )
            items = parse_results(data)

            if not items:
                break

            if keyword:
                items = search_keyword_in_records(items, keyword)

            for item in items:
                if len(records) >= max_items:
                    break
                records.append(item)

            total = get_total_count(data)
            if page * page_size >= total:
                break
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
        output_dir / sanitize_filename(f"tax_law_{label}", "tax_law")
    )
    write_jsonl(output_root / "metadata.jsonl", records)
    write_csv(output_root / "metadata.csv", records)

    cat_counts = {}
    for row in records:
        c = "未知"
        for cn, cc in CATEGORY_MAP.items():
            if cc and cc in (row.get("url", "")):
                c = cn
                break
        cat_counts[c] = cat_counts.get(c, 0) + 1

    stats = {
        "source": "tax_law",
        "keyword": keyword,
        "category": category,
        "record_count": len(records),
        "category_distribution": dict(sorted(cat_counts.items(), key=lambda x: -x[1])),
    }
    write_json(output_root / "stats_report.json", stats)

    md = render_markdown_report(
        f"税务法规库统计报告 - {label}",
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
        output_root / "summary.json", {"source": "tax_law", "count": len(records)}
    )
    return output_root


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="国家税务总局政策法规库搜索/下载工具",
        epilog=(
            "Categories: 全部, 法律, 行政法规, 国务院文件, 税务部门规章, "
            "财税文件, 税务规范性文件, 其他文件, 工作通知\n\n"
            "Examples:\n"
            "  python tax_law_crawler.py --search '增值税' --size 20\n"
            "  python tax_law_crawler.py --category 财税文件 --size 50\n"
            "  python tax_law_crawler.py --category 法律 --size 100\n"
            "  python tax_law_crawler.py --info 'https://fgk.chinatax.gov.cn/zcfgk/c102416/c5250687/content.html'\n"
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
        default="./tax_law_output",
        help="Output directory (default: ./tax_law_output)",
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
    logger = setup_logger(output_dir, name="tax_law_crawler")

    if args.no_cache:
        global _cache
        _cache = _CacheManager(enabled=False, namespace="tax-law-db")
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

    logger.info(
        "Start: keyword=%s, category=%s, size=%d", args.search, args.category, args.size
    )

    session = create_session()
    limiter.init_for_task(
        estimated_requests=max(1, args.size // 20 + 5), forced_mode=forced
    )

    records = search_collect(
        session,
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
        print(f"  {i}. {rec['title']}")
        if rec.get("document_number"):
            print(f"     文号: {rec['document_number']}")
        if rec.get("publish_time"):
            print(f"     时间: {rec['publish_time']}")
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
