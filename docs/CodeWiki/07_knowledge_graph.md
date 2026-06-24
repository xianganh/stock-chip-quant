# 07. 知识图谱

> 目录: [knowledgeGraph/](../../knowledgeGraph/)
> 统计: 约 168 个 .md 文件
> 详细规范: [NAMING_CONVENTION.md](../../knowledgeGraph/NAMING_CONVENTION.md) | [ontology.md](../../knowledgeGraph/ontology.md)

## 📚 设计理念

知识图谱是**用户维护的股票研究笔记**，已纳入项目 git 仓库，跨电脑自动同步。

通过 `GET /api/knowledge_graph/<code>` 端点暴露给 watchlist，用于选股时的关键词建议。

## 📂 目录结构

```
knowledgeGraph/
├── README.md              ← 编辑指南
├── NAMING_CONVENTION.md   ← 命名规范
├── ontology.md            ← 本体规范 (v2.0)
├── node_index.md          ← 节点索引
├── company/               ← 公司档案 (50 个 .md)
│   └── 元力股份_300174.md
├── concept/               ← 概念 (37 个)
├── technology/            ← 技术 (18 个)
├── sector/                ← 板块 (13 个)
├── component/             ← 部件/组件 (15 个)
├── event/                 ← 事件
├── supply_chain/          ← 供应链
├── topic/                 ← 话题
└── _workspace/            ← 草稿/证据池（不入 git）
    ├── 五洋自控_EvidencePool_v6.2.csv
    └── 博威合金_EvidencePool_v6.2.csv
```

## 🏷️ 节点类型（来自 ontology.md v2.0）

| 类型 | type_id | 说明 | 典型示例 |
|------|---------|------|---------|
| **产业链** | `industry_chain` | 顶层产业全景 | 商业航天产业链 |
| **技术/产品节点** | `tech_node` | 产业链中的具体技术/产品 | 火箭发动机推力室 |
| **供应链节点** | `supply_chain` | 聚焦单一客户/公司的供应商体系 | 新凯来供应链 |
| **个股节点** | `stock_node` | 上市公司个体 | 斯瑞新材 |
| **材料/平台节点** | `material_platform` | 横跨多个技术节点的材料/工艺 | 铜铬铌合金材料 |

## 📝 文件命名规范

### 公司档案

```
company/{公司名}_{股票代码}.md
```

**示例**：
- ✅ `company/元力股份_300174.md`
- ✅ `company/海目星_688559.md`
- ✅ `company/华为_未上市.md`（非上市公司用"未上市"代替代码）
- ❌ `海目星.md`（缺少代码、缺少目录前缀）

### 产业链/技术节点

```
supply_chain/{英文标识}_{可选中文}.md
technology/{英文标识}_{可选中文}.md
```

**示例**：
- ✅ `supply_chain/semiconductor_water_cooling.md`
- ✅ `technology/tgv_glass_via.md`
- ✅ `technology/玻璃基板_glass_substrate.md`（双语，英文在前）

### 人物节点

```
person/{姓名}_{职务}_{公司}.md
```

**示例**：
- ✅ `person/赵盛宇_实控人_海目星.md`

## 📄 文件格式（YAML Frontmatter）

每个 .md 文件必须有 frontmatter：

```markdown
---
node_id: 海目星_688559
node_name: 海目星
node_type: stock_node
stock_code: 688559.SH
industry: 激光设备/新能源装备
tags: [公司节点, 基础化工, 活性炭, 超级电容炭]
type: company
abstract_level: 1
code: 300174
name: 元力股份
related_nodes:
  - company/宁德时代_300750
  - supply_chain/semiconductor_water_cooling
schema_version: v2.1
updated_at: 2026-06-22
created: 2026-06-22
---

# 元力股份 (300174)

## 基本信息
- **全称**: 福建元力活性炭股份有限公司
- **主营业务**: 活性炭 78.59% / 硅酸钠 12.58%
...
```

### 关键字段

| 字段 | 必填 | 说明 |
|------|------|------|
| `tags` | ✓ | 关键词数组（用于选股时的建议）|
| `type` | | company / concept / technology 等 |
| `code` | 公司档案必填 | 6 位股票代码（不带后缀）|
| `name` | 公司档案必填 | 公司简称 |
| `abstract_level` | | 1=一句话, 2=详细 |
| `node_id` | v2.1+ | 唯一标识，与文件名（不含路径）一致 |
| `related_nodes` | v2.1+ | 双向链接的节点列表 |
| `schema_version` | v2.1+ | 本体规范版本 |
| `updated_at` | | 最后更新日期 |
| `created` | | 创建日期 |

## 🔗 Wiki Link 规范

```
[[路径/文件名（无扩展名）|显示名称]]
```

**示例**：
- ✅ `[[company/海目星_688559|海目星]]`
- ✅ `[[supply_chain/semiconductor_water_cooling|半导体设备水冷组件]]`
- ✅ `[[technology/tgv_glass_via|TGV玻璃通孔]]`
- ❌ `[[海目星]]`（缺少路径前缀）
- ❌ `[[company/海目星|海目星]]`（文件名错误，缺少代码）

## 🔍 系统读取流程

**位置**: [utils.py:348-457](../../utils.py#L348-L457)

### 启动时加载

```python
# Flask 启动时（首次 API 调用触发）
def load_knowledge_graph(kg_dir=None):
    # 1. 扫描 knowledgeGraph/**/*.md
    md_files = list(kg_path.rglob("*.md"))
    
    # 2. 解析每个文件的 frontmatter
    for md_file in md_files:
        text = md_file.read_text(encoding="utf-8")
        fm = _parse_frontmatter(text)
        
        # 3. 提取 code（优先 frontmatter，否则从文件名）
        code = str(fm.get("code", "")).strip()
        if not code or len(code) != 6 or not code.isdigit():
            code = _parse_filename_code(md_file.name)
        
        # 4. 建立索引
        _KG_INDEX[code] = {
            "code": code,
            "name": name,
            "tags": tags,
            "type": type,
            "summary": _extract_summary(text),
            "file": str(relative_path)
        }
```

### 索引结构

```python
_KG_INDEX: dict          # ts_code(6位) → {name, code, tags, abstract, file}
_KG_NAME_TO_CODE: dict   # name → ts_code（用于模糊搜索）
_KG_TAGS_INDEX: dict     # tag → [ts_code]（反向索引）
```

### 查询 API

```python
def get_kg_by_code(ts_code: str) -> dict:
    """按股票代码获取节点（自动补全交易所后缀）"""
    code6 = ts_code.split(".")[0]
    return _KG_INDEX.get(code6)
```

## 📊 API 端点

### `GET /api/knowledge_graph/<ts_code>`

**响应**:
```json
{
  "found": true,
  "code": "300174",
  "name": "元力股份",
  "tags": ["公司节点", "基础化工", "活性炭", "超级电容炭"],
  "type": "company",
  "summary": "福建元力活性炭股份有限公司...",
  "file": "company/元力股份_300174.md"
}
```

### `GET /api/knowledge_graph/<ts_code>/related`

按 tag 找关联公司（同一 tag 的其他股票）

**响应**:
```json
{
  "tags": ["活性炭", "超级电容炭"],
  "related": {
    "活性炭": [
      { "code": "300174", "name": "元力股份", "tags": [...] }
    ]
  }
}
```

### `GET /api/knowledge_graph/stats`

**响应**:
```json
{
  "loaded": true,
  "companies": 50,
  "tags": 187
}
```

## ✏️ 添加新公司流程

1. 在 `company/` 创建 `{公司名}_{代码}.md`
2. 使用 YAML frontmatter 模板
3. **重启 Flask** 或访问 `/api/knowledge_graph/stats` 触发重载
4. 在 watchlist 添加该代码，自动显示 tags

## 📈 维护建议

- **公司文档尽量详细**（基本面、产业链、竞争优势、预期差）
- **tags 简洁有力**（3-7 个关键词，不要太多）
- **定期清理 `_archive/`**（不纳入 git，留作历史）
- **每个新公司单独 .md**（便于精确按代码查询）
- **优先更新已有节点**（避免创建重复节点）

## 🚫 禁止操作

| 禁止操作 | 后果 | 正确做法 |
|---------|------|---------|
| 在根目录创建 `.md` 文件 | 图谱混乱，与 `company/` 下节点重复 | 统一放 `company/` 或 `supply_chain/` |
| 文件名不包含股票代码 | 难以识别，容易重复 | 必须包含 `_{代码}` |
| 链接不写路径前缀 | Obsidian 可能找不到或创建 stub | 必须写 `[[company/xxx_xxx|名称]]` |
| 创建报告文件作为节点 | 报告节点污染图谱 | 报告放 `_workspace/` |
| 同一节点有两个文件 | 图谱出现两个节点，链接混乱 | 删除重复，统一到一个文件 |

## 🛠️ 工具脚本

### `scripts/setup_knowledge_graph.py`

将外部 KG 目录复制到项目内：

```bash
python scripts/setup_knowledge_graph.py
```

**源**: `D:\stock\knowledgeGraph`
**目标**: `<项目根>/knowledgeGraph/`

**排除**: `_archive/`、`_meta/`、`index/`、`node_index.md`、`ontology.md`

---

## 📊 当前统计

| 类别 | 数量 |
|------|------|
| 公司 | 50+ |
| 概念 | 37 |
| 技术 | 18 |
| 板块 | 13 |
| 部件 | 15 |
| 事件 | 1+ |
| 供应链 | 1 |
| **合计** | **~168** |