# CN Law Hub

[![GitHub](https://img.shields.io/badge/GitHub-ZongziForu%2Fcn--law--hub-blue)](https://github.com/ZongziForu/cn-law-hub)

一个用于查询、检索、核验、下载、导出和批量采集中国官方法律数据的 Claude Code / Kimi Agent / Codex skill。

支持九个官方数据源：

1. **国家法律法规数据库 (NPC)** — `flk.npc.gov.cn`
2. **国家规章库 (Gov Rules)** — `gov.cn/zhengce/xxgk/gjgzk/`
3. **外交条约库 (Treaty)** — `treaty.mfa.gov.cn`
4. **国务院政策文件库** — `sousuo.www.gov.cn/zcwjk/policyDocumentLibrary`
5. **司法部行政法规库** — `xzfg.moj.gov.cn`
6. **党内法规库** — `www.12371.cn/special/dnfg/`
7. **国防部法规文库** — `www.mod.gov.cn/gfbw/fgwx/`
8. **税务法规库** — `fgk.chinatax.gov.cn`
9. **生态环境部法规标准** — `mee.gov.cn/ywgz/fgbz/`

> This is a Claude Code / Kimi Agent / Codex skill for searching, verifying, downloading, and exporting Chinese legal documents from the three official databases above. The official databases are Chinese-language sources; Chinese keywords and official titles usually produce the best results.

---

## 什么时候使用这个 Skill

当你需要查询、核验、下载或引用中国官方法律法规、规章、条约和具体法条时，可以直接让 agent 使用本 skill。多数情况下，你不需要手动运行脚本，只需要用自然语言说明任务，agent 会根据 `SKILL.md` 自动选择合适的数据源、脚本和参数。

如果你希望确保在当前工作中使用本 skill，也可以在请求中直接使用 `/cn-law-hub` 指令（尤其在你没有使用能力较强的模型时）。

典型场景包括：查法规全文、核验现行有效状态、查询某法第几条、按关键词检索具体法条、为法律咨询/案例分析/合规审查提供官方法条依据、批量下载法规文件或导出法规目录。

例如：

```text
帮我查《劳动合同法》第三十八条，并引用现行有效版本。
找一下关于物业管理的现行有效地方性法规。
帮我检索包含“违约金”的具体法条，并按法规名称列出来。
这个劳动争议案例可能涉及哪些现行有效法律依据？
```

<details>
<summary>更多可触发本 skill 的中文表达</summary>

你可以使用类似表达：

- 查法律、查法规、查条例、查规章、查条约、查法条
- 查第几条、查询某法第几条、找某条法律依据
- 找法律依据、引用法律依据、引用法条、展开法条分析
- 核验现行有效、判断是否废止、是否已修改、是否尚未生效
- 下载法规全文、批量下载法规文件、导出法规目录
- 按关键词检索具体法条、跨法规查找相关条文
- 查询地方性法规、按地区/制定机关分类
- 在法律咨询、案例分析、合规审查、合同审查、劳动争议、行政法分析、公司合规、数据合规、政策研究中，需要调用中国现行有效法律法规原文作为依据
- 当问题中出现“依法”“依规”“依照法律规定”“根据现行规定”等表达，并且需要核验具体法律依据时，也适合调用本 skill

如果只是一般法律概念解释、普通写作润色，且不需要核验官方法律法规原文，则不一定需要调用本 skill。

</details>

---

## 功能概览

- **多数据源支持**：NPC 国家法律法规数据库、国家规章库、外交条约库、国务院政策文件库、司法部行政法规库、党内法规库、国防部法规文库
- **标题/正文检索**：支持标题关键词、正文关键词两种搜索范围
- **精确/模糊策略**：已知标题用 `--exact` 精确匹配，主题/关键词用模糊匹配
- **现行有效状态筛选**：`--status 3` 仅返回现行有效法规
- **单篇下载**：DOCX（WPS 版）/ PDF（公报原版）
- **单条法条查询**：`--preview` 查看结构，`--article` 按条号或关键词查条文
- **跨法规法条级搜索**：`scripts/article_search.py` 在多部法规正文中定位具体法条
- **批量采集**：支持一次性采集 200–300 条法规的完整工作流
- **智能限速**：根据任务大小自动选择 OFF / FIXED / ADAPTIVE 模式，避免 429
- **本地缓存**：搜索结果、元数据、DOCX 文件默认缓存，复访提速
- **URL 导出**：云端 agent 可只导出签名下载 URL，供本地下载使用
- **地域/制定机关分类**：内置省市映射，自动识别国家级、省级、设区市级
- **多环境支持**：Kimi Agent、Claude Code via kimi-webbridge、Codex；其中 Kimi Agent 与 Claude Code via kimi-webbridge 共用同一套 browser adapter，因为两者的浏览器操作语义一致

---

## 安装

建议使用 Python 3.10+。

```bash
pip install -r requirements.txt
```

部分旧法规可能使用 `.doc` 格式，需要安装可选系统工具：

```bash
# macOS
brew install antiword catdoc

# Debian/Ubuntu
apt-get install antiword catdoc
```

---

## 快速开始

多数情况下，你不需要手动执行下面的命令。只要用自然语言向 agent 描述任务，agent 会根据 `SKILL.md` 自动选择合适的数据源、脚本和参数。

下面的命令主要用于本地手动运行、调试、复现结果，或帮助你理解本 skill 的核心能力。

### 国家法律法规数据库（NPC）

```bash
# 精确搜索已知法规名，并优先返回现行有效版本
python scripts/download.py --search "物业管理条例" --exact --status 3 --size 20

# 按主题/关键词模糊搜索
python scripts/download.py --search "出租车" --status 3 --size 50

# 下载单部法规
python scripts/download.py --download <bbbs_id> --format docx output.doc

# 查看法规结构并查询具体法条
python scripts/download.py --preview <bbbs_id>
python scripts/download.py --article <bbbs_id> "第三十八条"

# 跨法规检索具体法条
python scripts/article_search.py "违约金" --range content --max-laws 5 --context 1
```

### 国家规章库与外交条约库

```bash
# 国家规章库
python scripts/gov_rules_crawler.py --search "管理办法" --categories 部门规章 --size 20

# 外交条约库
python scripts/treaty_crawler.py --collections 双边 --search "上海合作组织" --size 20
```

更多参数见 [`SKILL.md`](SKILL.md) 和 [`references/`](references/)。

---

## 常见工作流

### 查询单条/多条法条

当你只需要核对某一条或搜索某部法规内的关键词时，不必把整部法规塞进 agent 上下文。

```bash
# 预览法规结构
python scripts/download.py --preview <bbbs_id>

# 按条号查询（自动识别中文/阿拉伯数字）
python scripts/download.py --article <bbbs_id> "第三十八条"
python scripts/download.py --article <bbbs_id> "第38条"
python scripts/download.py --article <bbbs_id> "38"

# 在单部法规中 grep 关键词
python scripts/download.py --article <bbbs_id> --grep "经济补偿"
```

### 跨法规法条级搜索

`scripts/article_search.py` 用于在多部法规中查找包含关键词的具体法条：

```bash
# 在标题含关键词的法规中搜索
python scripts/article_search.py "违约金" --max-laws 5 --context 1

# 在全文含关键词的法规中搜索
python scripts/article_search.py "违约金" --range content --max-laws 5

# 限定只查某一部法规
python scripts/article_search.py "善意取得" --law 民法典 --context 0

# JSON 输出
python scripts/article_search.py "违约金" --max-laws 3 --json

# 分批检索
python scripts/article_search.py "违约金" --range content --max-laws 5 --offset 5
python scripts/article_search.py "违约金" --range content --max-laws 5 --resume
```

### 智能限速与缓存

```bash
# 大任务使用自适应限速
python scripts/download.py --search "出租车" --urls-only --size 200 --rate-limit adaptive

# 查看缓存
python scripts/download.py --cache-stats

# 单次禁用缓存
python scripts/download.py --no-cache --info <bbbs_id>

# 清空缓存
python scripts/download.py --cache-clear
```

缓存位置：`~/.cache/npc-law-db/`

### 地域分类

城市级 authority 通常不含省份名，例如 "广州市人民代表大会常务委员会" 不会包含 "广东省"。`region_classifier.py` 自动处理这个问题：

```bash
python scripts/download.py --search "物业管理条例" --urls-only --size 100 > urls.json
python scripts/region_classifier.py --classify < urls.json > classified.json
python scripts/region_classifier.py --matrix matrix.csv < classified.json
```

<details>
<summary>Python API 示例</summary>

```python
from scripts.region_classifier import classify_by_authority

classify_by_authority("广州市人民代表大会常务委员会")
# {
#   "province": "广东省",
#   "province_short": "广东",
#   "city": "广州市",
#   "level": "city",
#   "is_municipality": False,
#   "authority": "广州市人民代表大会常务委员会"
# }
```

</details>

### 批量采集

详见 [`references/batch_collection.md`](references/batch_collection.md)。批量采集请使用自适应限速，并避免重复、大量、高频请求。

---

## 文件结构

```
cn-law-hub/
├── SKILL.md                      # 给 agent 看的 skill 主文档
├── README.md                     # 本文件
├── requirements.txt              # Python 依赖
├── scripts/
│   ├── common.py                 # 共享工具：缓存、限速、HTTP、文件 I/O
│   ├── download.py               # NPC 搜索、下载、导出 URL、预览/查询法条
│   ├── article_search.py         # NPC 跨法规法条级关键词搜索
│   ├── gov_rules_crawler.py      # 国家规章库爬虫
│   ├── treaty_crawler.py         # 外交条约库爬虫
│   └── region_classifier.py      # 地域分类与存在性矩阵
└── references/
    ├── api_reference.md          # NPC API 端点与参数参考
    ├── gov_rules_api_reference.md # 国家规章库 API 与认证参考
    ├── treaty_api_reference.md   # 外交条约库 HTML 结构参考
    ├── batch_collection.md       # 200-300 条批量采集指南
    ├── page_structure.md         # 页面结构说明
    ├── kimi_bridge_adapter.md    # Claude Code / Kimi Agent 适配
    └── codex_adapter.md          # Codex Chrome 插件适配
```

---

## 致谢

特别感谢 [Li2zon3](https://github.com/Li2zon3) 的 [`law-crawler-unified`](https://github.com/Li2zon3/law-crawler-unified) 项目，国家规章库（`scripts/gov_rules_crawler.py`）和外交条约库（`scripts/treaty_crawler.py`）的实现大量参考了其中的思路与方案，帮了很大的忙。

---

## 使用倡议

官方公共法律数据库的维护不易，请大家在使用时保持克制，尽量避免大量高频请求。**本项目在批量采集、搜索和下载等功能中已经内置了不同强度的智能限速（小任务关闭限速、中等任务固定限速、大任务自适应限速）**，希望在不明显影响使用体验的前提下，尽量减少对目标网站造成的负担。请珍惜并合理使用这些公开资源。

---

## 免责声明

本工具仅用于学习、研究、合规核验与个人/机构内部的辅助检索。请遵守 `flk.npc.gov.cn`、`gov.cn` 和 `treaty.mfa.gov.cn` 等官方数据库的使用规则，避免高频请求、重复批量抓取或对目标网站造成额外负担。

本项目的代码许可请以仓库中的 [LICENSE](LICENSE) 文件为准。需要特别声明的是，本项目不支持商业使用。这里所说的“不支持商业使用”，并非指代码本身不能用于商业活动环境（如律所办理案件的日常使用），而是指**不许可将本工具用于大量抓取官方法律数据库、镜像官方数据、转售数据、包装成收费数据服务或其他可能涉及官方数据再利用合规风险的商业化采集行为。**
上述行为因其访问量较大，可能影响目标网站正常运营，且带有盈利性，具有合规风险。使用者应自行评估其使用场景的合法性、合规性和对官方公共资源的影响。

本工具不提供法律意见，也不能替代律师、合规顾问或官方渠道的判断。对于法律文本的时效性、完整性和适用性，请以官方公布内容为准。

---

### 关于作者 / Contact

有任何问题欢迎随时交流！你可以从以下任何一种方式找到我～

| 平台       | 名称                      | 链接 / 联系方式                                               |
| ---------- | ------------------------- | ------------------------------------------------------------- |
| 小红书     | 只有肉粽子才算是粽子ney！ | [点击访问](https://xhslink.com/m/5XGgBInSyJc)                 |
| 微信公众号 | 正在施工的二层楼          | [点击访问](https://mp.weixin.qq.com/s/KUhM7u6ajCfLsw0KDXluZQ) |
| 邮箱       | —                         | `yqc0122@163.com`                                             |

---

<details>
<summary>English Summary</summary>

## What this project does

CN Law Hub is a Claude Code / Kimi Agent / Codex skill for searching, verifying, downloading, and exporting Chinese legal documents from three official databases:

- National Laws and Regulations Database (`flk.npc.gov.cn`)
- State Council Rules Database (`gov.cn/zhengce/xxgk/gjgzk/`)
- Ministry of Foreign Affairs Treaty Database (`treaty.mfa.gov.cn`)

## Installation

```bash
pip install -r requirements.txt
```

Optional: some older regulations use `.doc` format:

```bash
# macOS
brew install antiword catdoc

# Debian/Ubuntu
apt-get install antiword catdoc
```

## Quick Start

In most cases, you do not need to run these commands manually. Describe the task in natural language, and the agent will choose the appropriate database, script, and parameters based on SKILL.md.

The commands below are mainly for local manual use, debugging, reproducing results, or understanding the skill’s core capabilities.

```bash
# NPC: exact title search
python scripts/download.py --search "物业管理条例" --exact --status 3 --size 20

# NPC: article lookup
python scripts/download.py --article <bbbs_id> "第三十八条"

# NPC: article-level search across laws
python scripts/article_search.py "违约金" --range content --max-laws 5 --context 1

# State Council Rules
python scripts/gov_rules_crawler.py --search "管理办法" --categories 部门规章 --size 20

# MFA Treaties
python scripts/treaty_crawler.py --collections 双边 --search "上海合作组织" --size 20
```

The official databases are Chinese-language sources; Chinese keywords and official Chinese titles usually produce the best results.

## Disclaimer

The code license is governed by the repository [LICENSE](LICENSE). The recommendation against commercial use refers to large-scale extraction, mirroring, resale, or paid repackaging of official legal data, which may raise compliance risks. This tool does not provide legal advice; official publications remain authoritative.

</details>
