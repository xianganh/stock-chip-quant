# 知识图谱 (Knowledge Graph)

> 本目录包含**用户维护的股票研究笔记**, 已纳入本项目 git 仓库, 跨电脑自动同步.
> 通过 `GET /api/knowledge_graph/<code>` 端点暴露给 watchlist, 用于选股时的关键词建议.

---

## 📂 目录结构

```
knowledgeGraph/
├── README.md              ← 本文件
├── company/               ← 公司档案 (50 个 .md)
│   └── 元力股份_300174.md
├── concept/               ← 概念 (37 个)
├── technology/            ← 技术 (18 个)
├── sector/                ← 板块 (13 个)
├── component/             ← 部件/组件 (15 个)
├── event/                 ← 事件
├── supply_chain/          ← 供应链
├── topic/                 ← 话题
└── (根目录)              ← 跨分类主题
```

---

## 📝 文件命名规范

**公司档案**: `{公司名}_{代码}.md`
- 例: `元力股份_300174.md`
- 例: `长信科技_300088.md`

**概念/技术/板块等**: 自由命名
- 例: `AI算力.md`, `玻璃基板.md`, `球形硅微粉.md`

---

## 📄 文件格式 (YAML Frontmatter)

每个 .md 文件必须有 frontmatter, 提取 `tags` 作为关键词:

```markdown
---
tags: [公司节点, 基础化工, 活性炭, 超级电容炭, 球形硅微粉]
type: company
abstract_level: 1
code: 300174
name: 元力股份
created: 2026-06-22
---

# 元力股份 (300174)

## 基本信息
- **全称**: 福建元力活性炭股份有限公司
- **主营业务**: 活性炭 78.59% / 硅酸钠 12.58%
...
```

### 关键字段说明

| 字段 | 必填 | 说明 |
|------|------|------|
| `tags` | ✓ | 关键词数组 (用于选股时的建议) |
| `type` | | company / concept / technology 等 |
| `code` | 公司档案必填 | 6 位股票代码 (不带后缀) |
| `name` | 公司档案必填 | 公司简称 |
| `abstract_level` | | 1=一句话, 2=详细 |
| `created` | | 创建日期 |

---

## 🔄 跨电脑同步

**自动**: 通过 git push/pull, 见 [`../PROJECT.md`](../PROJECT.md) 的同步章节.

**手动复制** (如果你想自己管理):
```bash
# 复制到云盘 (例如 OneDrive)
cp -r knowledgeGraph ~/OneDrive/

# 在另一台电脑下载
cp -r ~/OneDrive/knowledgeGraph D:\stock\Analysis\
```

---

## 📊 系统如何读取

1. 启动 Flask 时, `utils.load_knowledge_graph()` 扫描此目录所有 .md 文件
2. 解析 frontmatter, 提取 `code` 和 `tags`
3. 构建索引: `{ts_code: {name, tags, summary, file}}`
4. 通过 API `/api/knowledge_graph/<code>` 查询
5. watchlist 编辑备注时显示 tags 作为建议

---

## ✏️ 如何添加新公司

1. 在 `company/` 创建 `{公司名}_{代码}.md`
2. 用以下模板:
   ```markdown
   ---
   tags: [公司节点, 行业标签, 概念标签, ...]
   type: company
   code: 300174
   name: 公司简称
   created: 2026-06-24
   ---

   # 公司名 (300174)

   ## 基本信息
   - ...
   ```
3. **重启 Flask** (或访问 `/api/knowledge_graph/stats` 触发重载)
4. 在 watchlist 添加 `300174`, 应自动显示新的 tags

---

## 💡 维护建议

- **公司文档尽量详细** (基本面、产业链、竞争优势、预期差)
- **tags 简洁有力** (3-7 个关键词, 不要太多)
- **定期清理 `_archive/`** (不纳入 git, 留作历史)
- **每个新公司单独 .md** (便于精确按代码查询)