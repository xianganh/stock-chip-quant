---
schema_version: v2.0
ontology_version: v2.0
updated_at: 2026-06-20
---

# 知识图谱本体规范（Ontology）

> 定义节点类型、属性、关系、验证规则，确保图谱结构一致、可扩展、可验证。

---

## 一、节点类型（Node Types）

| 类型 | type_id | 说明 | 典型示例 |
|------|---------|------|---------|
| **产业链** | industry_chain | 顶层产业全景，包含多个子节点 | 商业航天产业链、半导体设备零部件产业链 |
| **技术/产品节点** | tech_node | 产业链中的具体技术/产品/细分领域 | 火箭发动机推力室、光模块芯片基座 |
| **供应链节点** | supply_chain | 聚焦单一客户/公司的供应商体系 | 新凯来供应链 |
| **个股节点** | stock_node | 上市公司个体 | 斯瑞新材、富创精密 |
| **材料/平台节点** | material_platform | 横跨多个技术节点的材料/工艺平台 | （预留，如铜铬铌合金材料平台） |

---

## 二、属性规范（Properties）

### 2.1 必需属性（所有节点）

| 属性 | 类型 | 说明 | 示例 |
|------|------|------|------|
| node_id | string | 英文 snake_case，全局唯一 | `rocket_engine_thrust_chamber` |
| node_name | string | 中文名称，简洁准确 | `火箭发动机推力室` |
| schema_version | string | 本体版本，固定 `v2.0` | `v2.0` |
| updated_at | date | 最后更新日期 | `2026-06-20` |
| node_type | enum | 节点类型（见上文） | `tech_node` |

### 2.2 类型特定属性

#### 产业链（industry_chain）

| 属性 | 类型 | 说明 | 示例 |
|------|------|------|------|
| industry | string | 产业标识 | `commercial_space` |
| next_review | date | 下次 review 日期 | `2026-06-27` |

#### 技术/产品节点（tech_node）

| 属性 | 类型 | 说明 | 示例 |
|------|------|------|------|
| industry | string | 主产业归属 | `semiconductor_equipment` |
| category | enum | 产业链位置 | `upstream` / `midstream` / `downstream` / `cross_industry` |
| related_industries | list | 跨产业链引用 | `['commercial_space', 'semiconductor_equipment']` |
| aliases | list | 别名/同义词 | `['半导体设备散热组件', '刻蚀设备水冷']` |

#### 供应链节点（supply_chain）

| 属性 | 类型 | 说明 | 示例 |
|------|------|------|------|
| industry | string | 所属产业 | `semiconductor_equipment` |
| target_company | string | 目标客户名称 | `新凯来` |
| category | enum | 固定为 `supply_chain` | `supply_chain` |

#### 个股节点（stock_node）

| 属性 | 类型 | 说明 | 示例 |
|------|------|------|------|
| stock_code | string | 股票代码 | `688102.SH` |
| industry | string | 所属行业 | `新材料` / `半导体设备` |
| related_nodes | list | 关联的技术/产业链节点 | `['rocket_engine_thrust_chamber', 'optical_module_chip_base']` |

---

## 三、属性值规范（Enum 定义）

### 3.1 category（产业链位置）

| 值 | 适用类型 | 说明 |
|----|---------|------|
| upstream | tech_node | 上游（原材料/核心部件） |
| midstream | tech_node | 中游（制造/组装） |
| downstream | tech_node | 下游（应用/终端） |
| cross_industry | tech_node | 跨行业应用 |
| supply_chain | supply_chain | 供应链体系 |

### 3.2 industry（产业标识）

| 值 | 说明 | 使用节点 |
|----|------|---------|
| commercial_space | 商业航天 | 商业航天产业链及其子节点 |
| semiconductor_equipment | 半导体设备零部件 | 半导体设备零部件产业链及其子节点 |
| cross_industry | 跨行业 | 核聚变等跨领域节点（仅作标记，实际用 related_industries） |
| 新材料 | 新材料行业 | 斯瑞新材等个股 |

**重要规则**：
- `semiconductor_equipment` 用于半导体设备零部件产业链及其所有子节点
- `commercial_space` 用于商业航天产业链及其子节点
- 跨产业链节点（如半导体设备水冷组件同时被商业航天引用）→ 主产业用 `semiconductor_equipment`，通过 `related_industries` 标记跨引用

### 3.3 验证级别（⭐标记）

| 级别 | 含义 | 使用场景 |
|------|------|------|
| ⭐ | T1/T4 提及，无 T0 | 韭研/研报提及，无官方确认 |
| ⭐⭐ | T1 较明确 | 多家媒体报道 |
| ⭐⭐⭐ | T0 初步确认 | e互动/公司公告提及 |
| ⭐⭐⭐⭐ | T0 较明确 | 财报/招股书披露 |
| ⭐⭐⭐⭐⭐ | T0 完全确认 | 权威来源（年报、招股书、交易所公告） |

---

## 四、关系规范（Relationships）

### 4.1 隐含关系（通过 wikilink 自动建立）

```markdown
[[node_id|显示名]]  → 建立 "related_to" 关系
```

### 4.2 显式关系（未来扩展）

| 关系类型 | 从 | 到 | 说明 |
|----------|----|----|------|
| `belongs_to` | tech_node | industry_chain | 子节点属于某产业链 |
| `supplies` | stock_node | tech_node | 个股供应某技术节点产品 |
| `customer_of` | stock_node | stock_node | 客户-供应商关系 |
| `competes_with` | stock_node | stock_node | 竞争关系 |
| `material_basis_for` | material_platform | tech_node | 材料平台支撑技术节点 |
| `next_gen_of` | tech_node | tech_node | 技术代际关系 |

---

## 五、验证规则（Validation Rules）

### 5.1 创建前验证（必须全部通过）

| # | 规则 | 失败处理 |
|---|------|---------|
| 1 | node_id 全局唯一（不区分大小写） | 拒绝创建，使用现有节点 |
| 2 | node_name 不与现有节点同义 | 拒绝创建，使用别名/合并 |
| 3 | 子节点必须有明确的 industry | 拒绝创建 |
| 4 | 个股节点必须有 stock_code | 拒绝创建 |
| 5 | 供应链节点必须有 target_company | 拒绝创建 |
| 6 | schema_version 必须为 v2.0 | 自动修正 |
| 7 | node_type 必须匹配类型定义 | 拒绝创建 |

### 5.2 跨产业链引用验证

| # | 规则 | 说明 |
|---|------|------|
| 1 | 跨产业链引用时，必须在 related_industries 中标注 | 确保节点归属清晰 |
| 2 | 同一节点被多产业链引用时，node_id 不变 | 禁止为同一概念创建多个节点 |
| 3 | 引用节点不存在时，标记为 redlink（待创建） | 待创建节点需在 node_index 中登记 |

### 5.3 内容完整性验证

| # | 规则 | 说明 |
|---|------|------|
| 1 | 技术节点必须有"技术壁垒"章节 | 核心分析内容 |
| 2 | 技术节点必须有"市场容量"章节 | 定量分析基础 |
| 3 | 技术节点必须有"竞争格局"章节 | 标的筛选基础 |
| 4 | 个股节点必须有"关键数据"章节 | T0 验证数据 |
| 5 | 所有节点必须有"预期差标签" | 预期差分析核心 |
| 6 | 产业链节点必须有"关联个股"章节 | 反向查标的基础 |

---

## 六、文件命名规范

| 节点类型 | 文件名格式 | 示例 |
|----------|-----------|------|
| 产业链 | `{industry_name}产业链.md` | `商业航天产业链.md` |
| 技术节点 | `{node_id}.md` | `rocket_engine_thrust_chamber.md` |
| 供应链 | `{node_id}.md` | `xinkailai_supply_chain.md` |
| 个股 | `{股票全称}.md` | `斯瑞新材.md` |

---

## 七、frontmatter 模板

### 产业链模板

```yaml
---
node_id: xxx_industry
node_name: XXX产业链
node_type: industry_chain
industry: xxx
schema_version: v2.0
updated_at: 2026-06-20
next_review: 2026-06-27
---
```

### 技术节点模板

```yaml
---
node_id: xxx_xxx
node_name: XXX
node_type: tech_node
industry: xxx
# 如果是跨产业链：
related_industries: [xxx, yyy]
category: upstream|midstream|downstream|cross_industry
aliases: []
schema_version: v2.0
updated_at: 2026-06-20
---
```

### 供应链节点模板

```yaml
---
node_id: xxx_supply_chain
node_name: XXX供应链
node_type: supply_chain
industry: xxx
category: supply_chain
target_company: XXX
schema_version: v2.0
updated_at: 2026-06-20
---
```

### 个股节点模板

```yaml
---
node_id: 股票全称
node_name: 股票全称
node_type: stock_node
stock_code: xxxxxx.SH/SZ
industry: xxx
related_nodes:
  - node_id_1
  - node_id_2
schema_version: v2.0
updated_at: 2026-06-20
---
```

---

*本体规范维护：每次新增节点类型或属性时，必须更新本文件*
*位置：D:/stock/Analysis/knowledgeGraph/ontology.md*
