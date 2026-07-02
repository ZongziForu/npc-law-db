# 国务院政策文件库 API 参考

## 基本信息

- **URL**: `https://sousuo.www.gov.cn/zcwjk/policyDocumentLibrary`
- **API 端点**: `GET https://sousuo.www.gov.cn/search-gov/data`
- **认证**: 无
- **请求格式**: GET 参数
- **响应格式**: JSON

## 请求参数

| 参数           | 类型   | 默认值           | 说明                                                                        |
| -------------- | ------ | ---------------- | --------------------------------------------------------------------------- |
| `t`            | string | `zhengcelibrary` | 搜索主题                                                                    |
| `q`            | string | (必填)           | 搜索关键词                                                                  |
| `searchfield`  | string | `title`          | 搜索范围：`title`(标题) / `content`(全文)                                   |
| `sort`         | string | `score`          | 排序方式：`score`(相关度) / `pubtime`(时间)                                 |
| `sortType`     | int    | `1`              | 排序类型                                                                    |
| `p`            | int    | `0`              | 页码（从 0 开始）                                                           |
| `n`            | int    | `10`             | 每页数量                                                                    |
| `type`         | string | `gwyzcwjk`       | 文档类型                                                                    |
| `childtype`    | string |                  | 分类过滤：`gongwen`(国务院文件) / `bumenfile`(部门文件) / `otherfile`(解读) |
| `subchildtype` | string |                  | 子分类过滤                                                                  |
| `pubtimeyear`  | string |                  | 年份过滤（如 `2024`）                                                       |
| `bmfl`         | string |                  | 部门过滤（如 `国家发展和改革委员会`）                                       |
| `tsbq`         | string |                  | 标签过滤                                                                    |
| `timetype`     | string |                  | 时间类型                                                                    |
| `mintime`      | string |                  | 开始时间                                                                    |
| `maxtime`      | string |                  | 结束时间                                                                    |
| `pcodeJiguan`  | string |                  | 发文机关代码                                                                |
| `pcodeYear`    | string |                  | 文号年份                                                                    |
| `pcodeNum`     | string |                  | 文号编号                                                                    |
| `filetype`     | string |                  | 文件类型                                                                    |
| `inpro`        | string |                  | 是否在办                                                                    |
| `dup`          | string |                  | 是否重复                                                                    |
| `orpro`        | string |                  | 发文机关                                                                    |

## 响应结构

```json
{
  "code": 200,
  "msg": "操作成功",
  "data": null,
  "searchVO": {
    "totalCount": 35,
    "pageSize": 10,
    "currentPage": 0,
    "totalpage": 4,
    "catMap": {
      "gongwen": {
        "totalCount": 12,
        "catName": "gongwen",
        "currentNum": 10,
        "listVO": [
          {
            "piclinksurl": "https://www.gov.cn/...",
            "code": "",
            "pcode": "国办发〔2022〕35号",
            "source": "国务院办公厅",
            "title": "国务院办公厅关于复制推广<em>营商</em><em>环境</em>创新试点改革举措的通知",
            "pubtime": "1667206500000",
            "summary": "...",
            "content": "..."
          }
        ]
      },
      "bumenfile": { ... },
      "otherfile": { ... }
    },
    "extendresult": {
      "groupMap": { "国令": 1, "国发": 3, ... },
      "facetMap": {
        "tsbq": { "营商环境": 2, ... },
        "pubtimeyear": { "2024": 3, "2023": 8, ... },
        "bmfl": { "国家发展和改革委员会": "7条", ... }
      }
    }
  }
}
```

## 分类枚举

| childtype   | 说明                                     |
| ----------- | ---------------------------------------- |
| `gongwen`   | 国务院文件（国令、国发、国函、国办发等） |
| `bumenfile` | 国务院部门文件                           |
| `otherfile` | 解读                                     |

## 搜索建议

- **已知标题**：使用 `searchfield=title`（默认）缩小范围
- **模糊搜索**：使用 `searchfield=content` 搜索全文
- **部门过滤**：通过 `bmfl` 参数指定发文机关，如 `bmfl=国家发展和改革委员会`
- **年份过滤**：通过 `pubtimeyear` 参数，如 `pubtimeyear=2024`
