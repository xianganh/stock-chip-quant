# 知识图谱节点命名与写入规范

> 版本：v2.1
> 适用范围：D:/stock/Analysis/knowledgeGraph/ 目录下所有节点文件
> 目的：彻底避免节点重复、命名混乱、链接失效等问题

---

## 一、目录结构规范

| 目录 | 内容 | 说明 |
|------|------|------|
| `company/` | 所有股票节点（含上市公司、非上市公司、子公司） | 统一前缀：`company/` |
| `supply_chain/` | 产业链节点（如半导体、固态电池、AI算力等） | 按产业分类 |
| `technology/` | 技术概念节点（如TGV、MicroLED、玻璃基板等） | 技术细分 |
| `person/` | 人物节点（如实控人、董事长、核心科学家） | 重要人物 |
| `event/` | 事件节点（如并购、订单公告、政策变化） | 独立事件 |
| 根目录（`/`） | 仅保留：`_meta/`、`ontology.md`、`node_index.md`、README | **禁止在根目录放任何节点文件** |

---

## 二、文件命名规范（强制）

### 2.1 股票节点

```
company/{公司名}_{股票代码}.md
```

**示例**：
- ✅ `company/海目星_688559.md`
- ✅ `company/宁德时代_300750.md`
- ✅ `company/华为_未上市.md`（非上市公司用"未上市"代替代码）
- ❌ `海目星.md`（缺少代码、缺少目录前缀）
- ❌ `company/海目星.md`（缺少代码）
- ❌ `company/688559.md`（缺少公司名）
- ❌ `company/海目星_688559.md`（与 `company/海目星_688559.md` 实际是同一个文件，但之前容易混乱）

### 2.2 产业链/技术节点

```
supply_chain/{英文标识}_{可选中文}.md
technology/{英文标识}_{可选中文}.md
```

**示例**：
- ✅ `supply_chain/semiconductor_water_cooling.md`
- ✅ `technology/tgv_glass_via.md`
- ✅ `technology/玻璃基板_glass_substrate.md`（双语，英文在前）
- ❌ `固态电池.md`（缺少目录、缺少英文标识）
- ❌ `TGV.md`（缺少目录）

### 2.3 人物节点

```
person/{姓名}_{职务}_{公司}.md
```

**示例**：
- ✅ `person/赵盛宇_实控人_海目星.md`
- ❌ `赵盛宇.md`（缺少上下文）

---

## 三、Wiki Link 规范（强制）

### 3.1 链接格式

```
[[路径/文件名（无扩展名）|显示名称]]
```

**示例**：
- ✅ `[[company/海目星_688559|海目星]]`
- ✅ `[[supply_chain/semiconductor_water_cooling|半导体设备水冷组件]]`
- ✅ `[[technology/tgv_glass_via|TGV玻璃通孔]]`
- ❌ `[[海目星]]`（缺少路径前缀，Obsidian 可能找不到或创建重复节点）
- ❌ `[[company/海目星_688559]]`（缺少显示名称，可读性差）
- ❌ `[[海目星_688559|海目星]]`（缺少路径前缀，路径不唯一）
- ❌ `[[company/海目星|海目星]]`（文件名错误，缺少代码）

### 3.2 跨节点引用时必须先检查节点是否存在

**写入前检查流程**：
1. 先搜索 `D:/stock/Analysis/knowledgeGraph/**/*.md` 中是否有同名文件
2. 先检查 node_index.md 中是否有该节点
3. 确认存在后，使用准确的文件名链接

**错误示范**：之前创建的 `[[company/海目星_688559|海目星]]` 链接，但文件实际在根目录为 `海目星.md`，导致 Obsidian 创建灰色 stub 节点，与主节点重复。

---

## 四、写入前检查清单（强制执行）

### 4.1 脚本检查

已部署脚本：`D:/stock/Analysis/scripts/check_before_write.py`

**使用方法**：
```bash
cd D:/stock/Analysis/scripts
python check_before_write.py {stock_code} {node_name} {node_type}
```

**检查项**：
- 同股票代码是否已存在（YAML frontmatter 中的 stock_code）
- 同名节点是否已存在（跨目录检查）
- 相似名称是否已存在（如 "海目星" vs "海目星_688559"）
- 是否试图在根目录创建节点（禁止）
- 是否试图创建报告文件作为节点（禁止，报告放 `_workspace/`）

### 4.2 人工检查（脚本无法覆盖时）

1. **检查文件路径**：是否已存在 `company/xxx_xxx.md`
2. **检查 node_index.md**：是否已登记
3. **检查 Obsidian 图谱**：是否已有同名节点（关闭"显示未链接提及"后观察）
4. **检查 YAML frontmatter**：stock_code 是否准确

---

## 五、节点更新规范（避免重复）

### 5.1 更新已有节点（推荐）

**原则**：宁可修改已有节点，不要创建新节点。

**更新流程**：
1. 读取原节点文件
2. 在原有 YAML frontmatter 中更新 `updated_at` 时间
3. 追加新内容到对应章节
4. 保留原有链接不变

### 5.2 创建新节点（仅在确认不存在时）

**创建流程**：
1. 运行 `check_before_write.py` 确认不存在
2. 按命名规范创建文件
3. 在 `node_index.md` 中登记
4. 在相关节点中建立双向链接
5. 确认 Obsidian 图谱中只出现一个节点

### 5.3 禁止的操作

| 禁止操作 | 后果 | 正确做法 |
|---------|------|---------|
| 在根目录创建 `.md` 文件 | 图谱混乱，与 `company/` 下节点重复 | 统一放 `company/` 或 `supply_chain/` |
| 文件名不包含股票代码 | 难以识别，容易重复 | 必须包含 `_{代码}` |
| 链接不写路径前缀 | Obsidian 可能找不到或创建 stub | 必须写 `[[company/xxx_xxx|名称]]` |
| 创建报告文件作为节点 | 报告节点污染图谱 | 报告放 `D:/stock/Analysis/knowledgeGraph/_workspace/` |
| 同一节点有两个文件 | 图谱出现两个节点，链接混乱 | 删除重复，统一到一个文件 |
| 使用中文文件名（无英文标识） | 链接不稳定，容易重名 | 使用英文标识或中英双语 |

---

## 六、重复节点修复流程（应急）

若发现重复节点：

1. **确认主节点**：保留内容最完整、链接最多的文件
2. **合并内容**：将其他文件的内容合并到主节点
3. **更新链接**：全局搜索替换所有指向重复文件的链接
4. **删除重复文件**：确认无误后删除
5. **刷新 Obsidian**：关闭重新打开，确认图谱只有一个节点
6. **更新索引**：修改 `node_index.md` 中的路径

---

## 七、YAML frontmatter 规范

```yaml
---
node_id: 海目星_688559         # 唯一标识，与文件名一致（不含路径）
node_name: 海目星                # 中文显示名称
node_type: stock_node           # 类型：stock_node / concept_node / component_node / person_node / event_node
stock_code: 688559.SH          # 股票代码（A股加 .SH/.SZ/.BJ，非上市写"未上市"）
industry: 激光设备/新能源装备     # 行业分类
related_nodes:                   # 双向链接的节点列表
  - company/宁德时代_300750
  - supply_chain/semiconductor_water_cooling
  - technology/tgv_glass_via
schema_version: v2.1            # 本规范版本
updated_at: 2026-06-22          # 更新时间
---
```

**关键**：`node_id` 必须与文件名（不含路径和扩展名）完全一致。这是防止重复的核心机制。

---

## 八、附：命名示例对照表

| 公司 | 正确文件名 | 正确链接写法 | 错误示例 |
|------|-----------|-------------|---------|
| 海目星 | `company/海目星_688559.md` | `[[company/海目星_688559|海目星]]` | `海目星.md` / `[[海目星]]` |
| 宁德时代 | `company/宁德时代_300750.md` | `[[company/宁德时代_300750|宁德时代]]` | `宁德时代.md` / `[[company/宁德时代]]` |
| 北方华创 | `company/北方华创_002371.md` | `[[company/北方华创_002371|北方华创]]` | `company/北方华创.md` |
| 半导体水冷 | `supply_chain/semiconductor_water_cooling.md` | `[[supply_chain/semiconductor_water_cooling|半导体水冷]]` | `半导体水冷.md` |
| TGV | `technology/tgv_glass_via.md` | `[[technology/tgv_glass_via|TGV]]` | `TGV.md` |
| 赵盛宇 | `person/赵盛宇_实控人_海目星.md` | `[[person/赵盛宇_实控人_海目星|赵盛宇]]` | `赵盛宇.md` |

---

*规范制定：2026-06-22*
*版本：v2.1*
*用途：防止节点重复、命名混乱、链接失效*
