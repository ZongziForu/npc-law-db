---
name: cn-law-hub
description: >-
  用于查询、检索、核验、下载、导出、批量采集中国官方法律法规、规章、条约和具体法条。Use this skill aggressively when the user asks to 查法律、查法规、查条例、查规章、查条约、查法条、查第几条、找法律依据、引用法律依据、核验现行有效、判断是否废止/已修改/尚未生效、下载法规全文、导出法规目录、批量下载法规文件、按关键词检索具体法条、展开法条分析，或在中国法律咨询、案例分析、合规审查、合同审查、劳动争议、行政法分析、公司合规、数据合规、政策研究中需要调用、核验或引用中国现行有效法律法规原文作为依据。Trigger also when phrases such as 依法、依规、依照法律规定、法律法规 imply a need to verify specific statutory authority or article-level text. Covers 国家法律法规数据库 (flk.npc.gov.cn), 国家规章库 (gov.cn), 外交条约库 (treaty.mfa.gov.cn), 国务院政策文件库 (sousuo.www.gov.cn), 司法部行政法规库 (xzfg.moj.gov.cn), 党内法规库 (12371.cn), 国防部法规文库 (mod.gov.cn), 税务法规库 (fgk.chinatax.gov.cn), 生态环境部法规规章 (mee.gov.cn), and 最高人民法院发布栏目 (court.gov.cn). Supports 标题/正文检索, 精确/模糊检索, 时效性过滤, 分类过滤, 分页, 排序, 单篇下载, 批量下载, 法条级抽取, 地区/制定机关分类, and browser fallback. Trigger when the answer may depend on current effective Chinese statutes, regulations, rules, treaties, article text, official document status, or official source attribution. Do not use for purely general legal theory, generic writing, or legal reasoning that does not require retrieving or verifying official Chinese legal documents.
---

# Legal Databases Overview

This skill supports ten legal databases:

| Database                     | Script                          | Source                      | Data type         | Auth        |
| ---------------------------- | ------------------------------- | --------------------------- | ----------------- | ----------- |
| **国家法律法规数据库 (NPC)** | `scripts/download.py`           | `flk.npc.gov.cn`            | JSON API          | None        |
| **国家规章库 (Gov Rules)**   | `scripts/gov_rules_crawler.py`  | `gov.cn/zhengce/xxgk/gjgzk` | Athena API + HTML | Dynamic RSA |
| **外交条约库 (Treaty)**      | `scripts/treaty_crawler.py`     | `treaty.mfa.gov.cn`         | HTML scraping     | None        |
| **国务院政策文件库**         | `scripts/gov_policy_library.py` | `sousuo.www.gov.cn`         | REST API (GET)    | None        |
| **司法部行政法规库**         | `scripts/moj_law_crawler.py`    | `xzfg.moj.gov.cn`           | HTML scraping     | None        |
| **党内法规库**               | `scripts/party_law_crawler.py`  | `www.12371.cn`              | HTML scraping     | None        |
| **国防部法规文库**           | `scripts/mod_law_crawler.py`    | `www.mod.gov.cn`            | HTML scraping     | None        |
| **税务法规库**               | `scripts/tax_law_crawler.py`    | `fgk.chinatax.gov.cn`       | REST API (POST)   | Session     |
| **生态环境部法规规章**       | `scripts/mee_law_crawler.py`    | `mee.gov.cn`                | HTML scraping     | None        |
| **最高人民法院发布栏目**     | `scripts/court_law_crawler.py`  | `court.gov.cn`              | HTML scraping     | None        |

# National Laws and Regulations Database (国家法律法规数据库)

Official database: `https://flk.npc.gov.cn`. Maintained by NPC Standing Committee.

NPC helper scripts: use `scripts/download.py` for law-level search/download and `scripts/article_search.py` for article-level keyword extraction across laws.

## Environment Selection

This skill supports multiple agent environments. **Read the adapter for your environment first**:

| Environment                                | Read This                           | Tool prerequisite                                                       |
| ------------------------------------------ | ----------------------------------- | ----------------------------------------------------------------------- |
| **Kimi Agent (cloud)**                     | `references/kimi_bridge_adapter.md` | Native `mshtools-browser_*` tools                                       |
| **Claude Code (local via kimi-webbridge)** | `references/kimi_bridge_adapter.md` | Invoke `kimi-webbridge` first to obtain the same browser tool interface |
| **Codex**                                  | `references/codex_adapter.md`       | `mcp__node_repl__js` for browser control                                |

Kimi Agent and Claude Code via kimi-webbridge intentionally share the same adapter because their browser-operation semantics are the same.

## Project Setup

Install Python dependencies once. Old `.doc` parsing is mainly needed for some NPC legacy regulation files; DOCX parsing uses the Python stdlib.

```bash
pip install -r requirements.txt
# Optional: for old .doc format support (some regulations use pre-2007 Word format)
apt-get install antiword catdoc  # Linux
brew install antiword catdoc     # macOS
```

Page layout and browser automation details are in `references/page_structure.md`.

## Quick Reference

### API-First Search → Download Workflow (Recommended)

**The agent must decide the search strategy before calling the API.** Do not default to fuzzy for every query:

- **Known title / specific regulation** (e.g. "物业管理条例", "北京市生活垃圾管理条例"): use `--exact` (title + exact match) to reduce noise
- **Broad topic / unsure of title** (e.g. "出租车", "环境保护"): omit `--exact` to use fuzzy search
- **Ambiguous query**: ask the user whether they want exact title match or broad fuzzy match, or run both and compare

```bash
# 1. Fuzzy search by topic
python scripts/download.py --search "出租车" --size 100

# 2. Exact title search (less noise)
python scripts/download.py --search "物业管理条例" --exact --size 100

# 3. Search full text of laws
python scripts/download.py --search "违约金" --range content --size 50

# 4. Filter by effective status
python scripts/download.py --search "出租车" --status 3 --size 50

# 5. Get signed download URLs only (for local batch download)
python scripts/download.py --search "出租车" --urls-only --size 100 > urls.json

# 6. Get metadata
python scripts/download.py --info {bbbs_id}

# 7. Download file
python scripts/download.py --download {bbbs_id} --format docx output.doc
```

### Query Individual Articles (Preview / Article Lookup)

For retrieving specific articles instead of full files:

```bash
# Preview law structure — shows article count + numbering pattern + first 20 articles
python scripts/download.py --preview {bbbs_id}

# Query by article number (supports multiple formats, auto-converts)
python scripts/download.py --article {bbbs_id} "第三十八条"   # Chinese
python scripts/download.py --article {bbbs_id} "第38条"      # Arabic
python scripts/download.py --article {bbbs_id} "38"          # Number only

# Grep keyword across all articles of one law
python scripts/download.py --article {bbbs_id} --grep "经济补偿"
```

| Command             | Use when                                  | Output                                                |
| ------------------- | ----------------------------------------- | ----------------------------------------------------- |
| `--preview`         | Understand structure before querying      | Title, article count, numbering pattern, TOC          |
| `--article "第X条"` | Know the article number                   | Single article (supports Chinese/Arabic/auto-convert) |
| `--article --grep`  | Find all articles with keyword in one law | All matching articles                                 |

> If `--article` misses, read the detected numbering hint and run `--preview` before retrying.

### Search API

```
POST https://flk.npc.gov.cn/law-search/search/list
```

Working payload:

```json
{
  "searchRange": 1,
  "searchType": 2,
  "searchContent": "出租车",
  "pageNum": 1,
  "pageSize": 100,
  "orderByParam": { "order": "-1", "sort": "" },
  "flfgCodeId": [],
  "zdjgCodeId": [],
  "sxx": [],
  "gbrq": [],
  "sxrq": [],
  "gbrqYear": [],
  "xgzlSearch": false
}
```

| Field         | Meaning                                                           |
| ------------- | ----------------------------------------------------------------- |
| `searchRange` | `1`=标题, `2`=正文                                                |
| `searchType`  | `1`=精确, `2`=模糊                                                |
| `pageSize`    | Up to at least 100                                                |
| `sxx`         | Status filter: `1`=已废止, `2`=已修改, `3`=现行有效, `4`=尚未生效 |

Use the same strategy as the CLI workflow: exact or near-exact titles use `searchRange=1` + `searchType=1`; broad topic searches use `searchType=2`. Full parameters are in `references/api_reference.md`.

> **Browser fallback:** Use browser automation only when the API/script fails, when UI-only advanced search is required, or when the user explicitly requests UI operation; read `references/page_structure.md` first.

### Detail API (for metadata)

```
GET https://flk.npc.gov.cn/law-search/search/flfgDetails?bbbs={bbbs_id}
```

Returns: title, dates, category, status, and `ossFile` paths.

Use bundled script: `python scripts/download.py --info {bbbs_id}`

### Download API

```
GET https://flk.npc.gov.cn/law-search/download/pc?format={docx|pdf}&bbbs={bbbs_id}
```

Returns a signed OSS URL in `data.url`. Use that URL to download the actual file.

```bash
python scripts/download.py --download {bbbs_id} --format docx output.doc
```

> **Note:** The `ossFile` paths from the detail API are **not** directly downloadable. The site serves the SPA index page for those URLs. Always use the download API or browser download button.

### Article-Level Search (`scripts/article_search.py`)

For finding **specific articles** that contain a keyword (not just which laws):

```bash
# Search across laws whose titles contain keyword, find matching articles
python scripts/article_search.py "违约金" --max-laws 5

# Search across laws whose full text contains keyword
python scripts/article_search.py "违约金" --range content --max-laws 5

# Show surrounding context (1 article before/after each match)
python scripts/article_search.py "抵押权" --range content --max-laws 3 --context 1

# Search within a specific law only
python scripts/article_search.py "善意取得" --law "民法典" --context 0

# JSON output for further processing
python scripts/article_search.py "违约金" --max-laws 3 --json
```

| Parameter               | Default         | Description                              |
| ----------------------- | --------------- | ---------------------------------------- |
| `keyword`               | (required)      | Keyword to search within articles        |
| `--law`                 | same as keyword | Keyword to find candidate laws           |
| `--range title/content` | title           | Search law titles or full text           |
| `--max-laws`            | 5               | Max laws to download and parse           |
| `--context`             | 0               | Surrounding articles to include          |
| `--status`              | all             | Filter by status code                    |
| `--json`                |                 | Output JSON instead of text              |
| `--offset`              | 0               | Skip first N laws (batch retrieval)      |
| `--resume`              |                 | Skip laws whose DOCX is already in cache |

**Progressive Batch Retrieval:** use `--offset N` to skip already-processed laws, or `--resume` to auto-skip cached ones:

```bash
# Batch 1: process first 5 laws
python scripts/article_search.py "违约金" --range content --max-laws 5
# → "已处理: 5/342 部法规"

# Batch 2: skip first 5 laws, then process laws 6-10
python scripts/article_search.py "违约金" --range content --max-laws 5 --offset 5

# Or: use --resume to skip already-processed laws and continue with new ones
python scripts/article_search.py "违约金" --range content --max-laws 5 --resume
```

### Authority / Region Categorization

Use `region_classifier.py` for province/city/level classification when issuing authority names (`zdjgName`) are irregular; prefer official `zdjgfl` codes from `GET /law-search/search/enumData` when available.

```bash
python scripts/download.py --search "物业管理条例" --urls-only --size 100 > urls.json
python scripts/region_classifier.py --classify < urls.json > classified.json
python scripts/region_classifier.py --matrix matrix.csv < classified.json
```

### NPC Rate Limiting

Auto mode (default) picks the mode by estimated request count:

| Mode         | Trigger         | Speed                       |
| ------------ | --------------- | --------------------------- |
| **OFF**      | ≤10 requests    | Unlimited                   |
| **FIXED**    | 11–100 requests | 5 req/s                     |
| **ADAPTIVE** | >100 requests   | 1–8 req/s, backs off on 429 |

Override: `--rate-limit fixed/adaptive/off/N` (N = custom req/s).

### NPC Cache Management

Local file cache enabled by default (`~/.cache/npc-law-db/`). Use `--cache-stats` / `--cache-clear` / `--no-cache`.

| Cache Type      | TTL        |
| --------------- | ---------- |
| Search results  | 1 hour     |
| Detail metadata | 24 hours   |
| DOCX files      | 7 days     |
| Signed URLs     | not cached |

## NPC Status Code Mapping (sxx field)

| sxx | Status       |
| --- | ------------ |
| `1` | **已废止**   |
| `2` | **已修改**   |
| `3` | **现行有效** |
| `4` | **尚未生效** |

---

# 国务院政策文件库 (State Council Policy Document Library)

**Source:** `https://sousuo.www.gov.cn/zcwjk/policyDocumentLibrary`

Covers State Council documents, departmental documents, and policy interpretations.

**Script:** `scripts/gov_policy_library.py`

### Quick Reference

```bash
# Search by keyword
python scripts/gov_policy_library.py --search "营商环境" --size 20

# Search full text
python scripts/gov_policy_library.py --search "放管服" --range content --size 50

# Filter by category
python scripts/gov_policy_library.py --search "国务院" --category 国务院文件 --size 100

# Filter by year
python scripts/gov_policy_library.py --search "营商环境" --year 2024 --size 50

# Fetch detail page
python scripts/gov_policy_library.py --info "https://www.gov.cn/gongbao/content/xxx.htm"
```

### API Details

```
GET https://sousuo.www.gov.cn/search-gov/data
```

| Parameter     | Default          | Description                                                                      |
| ------------- | ---------------- | -------------------------------------------------------------------------------- |
| `t`           | `zhengcelibrary` | Search topic                                                                     |
| `q`           | (required)       | Search keyword                                                                   |
| `searchfield` | `title`          | `title` or `content`                                                             |
| `sort`        | `score`          | `score` or `pubtime`                                                             |
| `p`           | `0`              | Page number (0-based)                                                            |
| `n`           | `10`             | Page size                                                                        |
| `type`        | `gwyzcwjk`       | Document type                                                                    |
| `childtype`   |                  | Category filter: `gongwen`(国务院文件), `bumenfile`(部门文件), `otherfile`(解读) |
| `pubtimeyear` |                  | Filter by year (e.g. `2024`)                                                     |
| `bmfl`        |                  | Filter by department name                                                        |

---

# 司法部行政法规库 (MoJ Administrative Regulations)

**Source:** `https://xzfg.moj.gov.cn/search2.html`

Official administrative regulations database maintained by the Ministry of Justice.

**Script:** `scripts/moj_law_crawler.py`

```bash
# Search by keyword
python scripts/moj_law_crawler.py --search "营商环境" --size 20

# Search full text
python scripts/moj_law_crawler.py --search "行政复议" --range content --size 50

# Filter by effective status
python scripts/moj_law_crawler.py --search "行政处罚" --status effective --size 100
```

**Note:** This is a server-side rendered HTML site. Results are parsed from HTML pages.

---

# 党内法规库 (Party Regulations - 12371.cn)

**Source:** `https://www.12371.cn/special/dnfg/`

Covers CCP internal regulations: 党章, 条例, 规定, 办法, 规则, 细则, and more.

**Script:** `scripts/party_law_crawler.py`

```bash
# Search across all categories
python scripts/party_law_crawler.py --search "纪律" --size 20

# Filter by category
python scripts/party_law_crawler.py --category 条例 --size 50

# Fetch detail
python scripts/party_law_crawler.py --info "https://www.12371.cn/2022/01/23/ARTI1642937162249109.shtml"
```

**Categories:** 全部, 党章, 条例, 规定, 办法, 规则, 细则, 党的组织法规, 党的领导法规, 党的自身建设法规, 党的监督保障法规

**Note:** This site uses static HTML pages with no search API. Keyword filtering is done client-side on titles.

---

# 国防部法规文库 (MOD Law Library)

**Source:** `http://www.mod.gov.cn/gfbw/fgwx/index.html`

Covers military/defense regulations, white papers, judicial interpretations, and publications.

**Script:** `scripts/mod_law_crawler.py`

```bash
# Search by keyword
python scripts/mod_law_crawler.py --search "军队" --size 20

# Filter by category
python scripts/mod_law_crawler.py --category 法律法规 --size 50

# Fetch detail
python scripts/mod_law_crawler.py --info "http://www.mod.gov.cn/gfbw/fgwx/flfg/16448581.html"
```

**Categories:** 全部, 法律法规, 白皮书, 文件, 司法解释, 出版物, 热点聚焦, 政策解读

**Note:** This site uses static HTML pages with no search API. Keyword filtering is done client-side on titles.

---

# 税务法规库 (Tax Regulations - fgk.chinatax.gov.cn)

**Source:** `https://fgk.chinatax.gov.cn/`

Covers tax-related laws, regulations, departmental rules, and fiscal/tax documents from the State Taxation Administration.

**Script:** `scripts/tax_law_crawler.py`

```bash
# Search by keyword across all categories
python scripts/tax_law_crawler.py --search "增值税" --size 20

# Filter by category
python scripts/tax_law_crawler.py --category 财税文件 --size 50

# Fetch detail
python scripts/tax_law_crawler.py --info "https://fgk.chinatax.gov.cn/zcfgk/c102416/c5250687/content.html"
```

**Categories:** 全部, 法律, 行政法规, 国务院文件, 税务部门规章, 财税文件, 税务规范性文件, 其他文件, 工作通知

### API Details

```
POST https://www.chinatax.gov.cn/getFileListByCodeId
```

| Parameter   | Description                                    |
| ----------- | ---------------------------------------------- |
| `codeId`    | Category code (e.g., `c100009` for 法律)       |
| `channelId` | Dynamic channel ID (auto-discovered from page) |
| `page`      | Page number (1-based)                          |
| `size`      | Page size (up to 20)                           |

**Note:** Requires a session cookie obtained by visiting the site first. The script handles this automatically.

---

# 生态环境部法规规章 (MEE Regulations - mee.gov.cn)

**Source:** `https://www.mee.gov.cn/ywgz/fgbz/`

Covers environmental laws, regulations, and rules from the Ministry of Ecology and Environment.

**Script:** `scripts/mee_law_crawler.py`

```bash
# Search by keyword across all categories
python scripts/mee_law_crawler.py --search "碳" --size 20

# Filter by category
python scripts/mee_law_crawler.py --category 法律 --size 50

# Fetch detail
python scripts/mee_law_crawler.py --info "https://www.mee.gov.cn/ywgz/fgbz/fl/202603/t20260313_1146496.shtml"
```

**Categories:** 全部, 法律, 行政法规, 规章, 生态环境损害赔偿制度, 行政复议与执法解释

**Note:** This site uses static HTML pages. All tabs are pre-loaded in the main page HTML. Keyword filtering is done client-side on titles. 标准(环保标准)不包含在本数据源中。

---

# 最高人民法院发布栏目 (Supreme People's Court - court.gov.cn)

**Source:** `https://www.court.gov.cn/fabu.html`

Covers judicial interpretations, judicial documents, major cases, and notices from the Supreme People's Court.

**Script:** `scripts/court_law_crawler.py`

```bash
# Search by keyword across 司法解释 and 司法文件
python scripts/court_law_crawler.py --search "建设工程" --size 20

# Filter by category
python scripts/court_law_crawler.py --category 司法解释 --size 50
python scripts/court_law_crawler.py --category 司法文件 --size 30

# Fetch detail
python scripts/court_law_crawler.py --info "https://www.court.gov.cn/fabu/xiangqing/504221.html"
```

**Categories:** 全部(司法解释+司法文件), 司法解释, 司法文件, 重大案件, 通知, 司法数据, 大数据专题, 标准化工作, 任免招录, 开庭公告

| category code | Category name |
|---------------|--------------|
| `16` | 司法解释 |
| `17` | 司法文件 |
| `15` | 重大案件 |
| `22` | 通知 |
| `21` | 司法数据 |
| `662` | 大数据专题 |
| `108` | 标准化工作 |
| `79` | 任免招录 |
| `14` | 开庭公告 |

**Note:** List pages use pagination (`/fabu/gengduo/{id}.html` → `{id}_{n}.html`). Keyword filtering is done client-side on titles.

---

Filter by status: `--status 3` (only current), `--status 3,4` (current + upcoming)

Key NPC concepts: `bbbs` is the unique law ID used in detail URLs and script commands; `sxx` is the effective-status field (`1`=已废止, `2`=已修改, `3`=现行有效, `4`=尚未生效).

When the task requires sorting, category codes, download options, advanced search, batch UI actions, or pagination parameters, read `references/api_reference.md`.

---

## State Council Rules Database (国家规章库)

Official database: `https://www.gov.cn/zhengce/xxgk/gjgzk/`. Maintained by the State Council.

### Quick Start

```bash
# Search department rules
python scripts/gov_rules_crawler.py --search "管理办法" --categories 部门规章 --size 20

# Search local government rules
python scripts/gov_rules_crawler.py --search "物业管理" --categories 地方政府规章 --size 20

# Get metadata for a specific page
python scripts/gov_rules_crawler.py --info "https://www.gov.cn/zhengce/202606/content_7073180.htm"

# Download full pages and attachments
python scripts/gov_rules_crawler.py --categories 部门规章 --size 10 --download
```

### Output

Output includes `summary.json`, `metadata.jsonl/csv`, `stats_report.json/md`, `logs/`, and downloaded files under `files/{rule_title}/`.

### Notes

- The Athena API requires dynamic RSA authentication discovered from the frontend JS bundle.
- Auth parameters may expire during long runs; restart if you receive 401/403.
- Read `references/gov_rules_api_reference.md` for the full auth and API field mapping.

---

## Ministry of Foreign Affairs Treaty Database (外交条约库)

Official database: `https://treaty.mfa.gov.cn/web/`. Maintained by the Ministry of Foreign Affairs.

### Quick Start

```bash
# Search bilateral treaties
python scripts/treaty_crawler.py --collections 双边 --search "上海合作组织" --size 20

# Search multilateral treaties
python scripts/treaty_crawler.py --collections 多边 --search "人权" --size 20

# Get metadata for a specific treaty page
python scripts/treaty_crawler.py --info "https://treaty.mfa.gov.cn/web/detail1.jsp?objid=1531876373617"

# Download treaty preview PDFs
python scripts/treaty_crawler.py --collections 双边 --size 5 --download
```

### Output

Output includes `summary.json`, `metadata.jsonl/csv`, `stats_report.json/md`, `logs/`, and preview PDFs under `files/{treaty_title}_{collection}/`.

### Notes

- This is a pure HTML site; parsing relies on BeautifulSoup.
- Collections: `全部` (all), `双边` (bilateral), `多边` (multilateral).
- Read `references/treaty_api_reference.md` for HTML structure and field extraction patterns.

---

All crawler scripts support `--no-cache` and `--rate-limit {off|fixed|adaptive}`; use adaptive mode for large collection tasks.

## Script Reference Summary

| Script                         | Purpose                              | Key CLI                                                                     | Output              |
| ------------------------------ | ------------------------------------ | --------------------------------------------------------------------------- | ------------------- |
| `scripts/download.py`          | NPC laws/regulations                 | `--search`, `--info`, `--download`, `--preview`, `--article`, `--urls-only` | stdout, files       |
| `scripts/article_search.py`    | Article-level search across NPC laws | `keyword`, `--law`, `--range`, `--max-laws`, `--context`, `--json`          | stdout              |
| `scripts/gov_rules_crawler.py` | Gov.cn rules database                | `--search`, `--categories`, `--size`, `--download`, `--info`                | `gov_rules_output/` |
| `scripts/treaty_crawler.py`    | MFA treaty database                  | `--search`, `--collections`, `--size`, `--download`, `--info`               | `treaty_output/`    |
| `scripts/region_classifier.py` | Province/city classification         | `--classify`, `--matrix`                                                    | JSON/CSV            |

---

## Attribution

Special thanks to [Li2zon3]for the [`law-crawler-unified`]project.
