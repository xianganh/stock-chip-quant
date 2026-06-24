---
type: node_index
schema_version: v2.0
ontology_version: v2.0
updated_at: 2026-06-24
---

# 知识图谱节点索引（v2.1 路径迁移版）

> 核心原则：**名称不同但内涵一样的节点必须合并，避免图谱冗余和认知混乱。**
> 图谱根目录已迁移至：`D:/stock/Analysis/knowledgeGraph/`

---

## 一、已注册节点清单（整合后）

### 1.1 company/ 目录

| 节点 | 代码 | 类型 | 状态 | 备注 |
|------|------|------|------|------|
| company/斯瑞新材_688102.md | 688102.SH | 个股 | content | 主节点 |
| company/顺络电子_002138.md | 002138.SZ | 个股 | content | |
| company/北方华创_002371.md | 002371.SZ | 个股 | stub | |
| company/拓荆科技_688072.md | 688072.SH | 个股 | content | |
| company/中微公司_688012.md | 688012.SH | 个股 | stub | |
| company/三祥新材_603663.md | 603663.SH | 个股 | content | 预期差分析 v6.1 |
| company/九安医疗_002432.md | 002432.SZ | 个股 | content | 预期差分析 v6.1 |
| company/大元泵业_603757.md | 603757.SH | 个股 | content | 预期差分析 v6.1 |
| company/博威合金_601137.md | 601137.SH | 个股 | content | 预期差分析 v6.1 |
| company/宏柏新材_605366.md | 605366.SH | 个股 | content | 预期差分析 v6.1 |

### 1.2 component/ 目录

| 节点 | 类型 | 状态 | 备注 |
|------|------|------|------|
| component/光模块.md | 元件 | content | 已合并芯片基座 |
| component/半导体设备.md | 元件 | stub | |
| component/刻蚀.md | 元件 | stub | |
| component/薄膜沉积.md | 元件 | stub | |
| component/电感.md | 元件 | content | |
| component/被动元件.md | 元件 | content | |

### 1.3 sector/ 目录

| 节点 | 类型 | 状态 | 备注 |
|------|------|------|------|
| sector/商业航天.md | 产业链 | content | 主节点 |
| sector/核聚变.md | 产业链 | content | 主节点 |
| sector/半导体设备零部件.md | 产业链 | content | 主节点 |
| sector/铜合金.md | 板块 | content | |
| sector/数据中心.md | 板块 | content | |
| sector/AI服务器.md | 板块 | content | |

### 1.4 concept/ 目录

| 节点 | 类型 | 状态 |
|------|------|------|
| concept/国产替代.md | 概念 | content |

### 1.5 event/ 目录

| 节点 | 类型 | 状态 |
|------|------|------|
| event/2026-06-15_顺络业绩预告.md | 事件 | content |

### 1.6 v2.0 体系节点（根目录，无 v5.6 对应）

| node_id | node_name | 类型 | 状态 | 说明 |
|---------|----------|------|------|------|
| rocket_engine_thrust_chamber | 火箭发动机推力室 | 技术节点 | content | 无 v5.6 对应 |
| semiconductor_water_cooling | 半导体设备水冷组件 | 技术节点 | content | 跨产业链 |
| semiconductor_mechanical_parts | 半导体设备机械类零部件 | 技术节点 | content | 无 v5.6 对应 |
| semiconductor_ceramic_parts | 半导体设备陶瓷类零部件 | 技术节点 | content | 2026-06-20 创建 |
| semiconductor_gas_system | 半导体设备气体管路/阀门 | 技术节点 | content | 2026-06-20 创建 |
| semiconductor_sputtering_target | 半导体设备溅射靶材 | 技术节点 | content | 2026-06-20 创建 |
| semiconductor_electrical_parts | 半导体设备机电一体/射频电源 | 技术节点 | content | 2026-06-20 创建 |
| semiconductor_optical_parts | 半导体设备光学元件 | 技术节点 | content | 2026-06-20 创建 |
| xinkailai_supply_chain | 新凯来供应链 | 供应链 | content | 无 v5.6 对应 |
| 富创精密 | 富创精密 | 个股 | content | 无 v5.6 对应 |
| 新莱应材 | 新莱应材 | 个股 | content | 无 v5.6 对应 |

### 1.7 重定向文件

| 文件 | 重定向目标 |
|------|-----------|
| 斯瑞新材.md | company/斯瑞新材_688102.md |
| 商业航天产业链.md | sector/商业航天.md |
| nuclear_fusion_components.md | sector/核聚变.md |
| 半导体设备零部件产业链.md | sector/半导体设备零部件.md |
| optical_module_chip_base.md | component/光模块.md |

---

## 二、去重规则（核心规范）

### 2.1 创建新节点前的检查清单

```
□ Step 1: 检查 v5.6 体系是否已有对应节点
   - 查 company/、component/、sector/、concept/ 目录
   - 如果已有类似节点 → 判断是否需要合并或引用

□ Step 2: 检查 v2.0 体系是否已有对应节点
   - 查 node_index.md "已注册节点清单"
   - 如果 node_id 已存在 → 不创建，直接使用 wikilink 引用

□ Step 3: 检查 node_name 是否已有相似概念
   - 如果新名称是现有名称的"子集" → 不创建新节点，在现有节点中增加细分章节
   - 如果新名称是现有名称的"超集" → 不创建，超集节点与现有层级冲突
   - 如果新名称与现有名称"同义不同字" → 不创建，选择最准确名称，用 alias 标记

□ Step 4: 确认命名符合规范
   - v5.6 规范：company/公司名_代码.md、component/元件名.md、sector/板块名.md
   - v2.0 规范：node_id 英文 snake_case（用于无 v5.6 对应的技术节点）

□ Step 5: 确认节点层级
   - 顶层：产业/板块（sector/）
   - 中层：技术/产品/元件（component/ 或 v2.0 技术节点）
   - 底层：个股（company/）
   - 同一层级不能重复，不同层级可以引用
```

### 2.2 禁止创建的情况

| 场景 | 示例 | 处理方式 |
|------|------|---------|
| 同义不同名 | 已创建"光模块"，再创建"光模块底座" | 禁止。选择最准确名称，在节点中标注别名 |
| 子集重复 | 已有"光模块"，再创建"800G光模块" | 禁止。在现有节点中增加"800G/1.6T"细分章节 |
| 超集重复 | 已有"半导体设备零部件"，再创建"半导体设备" | 禁止。超集节点与现有层级冲突 |
| 个股vs概念混淆 | 已有"斯瑞新材"，再创建"斯瑞新材水冷业务" | 禁止。个股节点内用章节区分业务 |
| 跨体系重复 | v5.6 已有 `company/斯瑞新材_688102.md`，再创建 `斯瑞新材.md` | 禁止。内容合并到 v5.6 节点 |
| 时间维度重复 | 已有"新凯来供应链"，再创建"2026年新凯来供应商" | 禁止。时间维度用关键变量追踪中的日期标记 |

### 2.3 允许创建的情况

| 场景 | 示例 | 原因 |
|------|------|------|
| 跨产业链复用 | "半导体设备水冷组件"同时被商业航天和半导体产业链引用 | 同一节点，多产业链引用 |
| 个股天然独立 | 不同个股（如斯瑞新材 vs 富创精密） | 个股是独立实体 |
| 供应链独立节点 | "新凯来供应链" | 特定客户的生态映射 |
| v2.0 技术节点无 v5.6 对应 | "火箭发动机推力室" | 保留 v2.0 节点 |

---

## 三、命名规范

### 3.1 v5.6 体系命名（主规范）

| 类型 | 命名格式 | 目录 | 示例 |
|------|---------|------|------|
| 公司 | `公司名_代码.md` | company/ | `company/斯瑞新材_688102.md` |
| 元件/产品 | `元件名.md` | component/ | `component/光模块.md` |
| 板块/产业链 | `板块名.md` | sector/ | `sector/商业航天.md` |
| 概念 | `概念名.md` | concept/ | `concept/国产替代.md` |
| 事件 | `YYYY-MM-DD_事件摘要.md` | event/ | `event/2026-06-15_顺络业绩预告.md` |

### 3.2 v2.0 技术节点命名（补充规范）

| 类型 | 命名格式 | 目录 | 示例 |
|------|---------|------|------|
| 技术/产品节点 | `{product}_{detail}.md` | 根目录（无 v5.6 对应时） | `rocket_engine_thrust_chamber.md` |
| 供应链节点 | `{company}_supply_chain.md` | 根目录 | `xinkailai_supply_chain.md` |
| 个股（无 v5.6 对应） | `股票全称.md` | 根目录 | `富创精密.md` |

**规则**：
- 优先使用 v5.6 命名规范和目录结构
- 仅当 v5.6 无对应节点时，使用 v2.0 命名规范
- 创建后应在 node_index.md 中登记，并标注与 v5.6 的关系

---

## 四、跨体系引用规范

### 4.1 v5.6 引用 v2.0 节点

```markdown
| [[technology/rocket_engine_thrust_chamber|火箭发动机推力室]] | 中游 | ... |
```

### 4.2 v2.0 引用 v5.6 节点

```markdown
| [[company/斯瑞新材_688102|斯瑞新材]] | 688102.SH | ... |
| [[component/光模块|光模块]] | ... | ... |
```

### 4.3 重定向文件引用

重定向文件保留原有文件名，内部仅包含指向主节点的链接：
```markdown
> ⚠️ 内容已合并至 [[company/斯瑞新材_688102]] — 保留本文件以维持历史引用
```

---

## 五、别名管理（同义不同名的处理）

如果一个概念有多个常用名称，在节点中统一使用最准确的名称，并标注别名：

```markdown
---
node_id: semiconductor_water_cooling
node_name: 半导体设备水冷组件
aliases:
  - 半导体设备散热组件
  - 刻蚀设备水冷
  - CVD设备散热
---

# 半导体设备水冷组件

> 别名：半导体设备散热组件、刻蚀设备水冷、CVD设备散热
```

**禁止**：为每个别名创建独立节点文件。

---

## 六、去重检查流程（新增节点时必做）

```
1. 打开本索引文件（node_index.md）
2. 搜索 node_id：是否已存在？
   - 是 → 停止创建，使用现有节点
3. 搜索 node_name（关键词）：是否有相似概念？
   - 是 → 判断是否"子集/超集/同义"关系
     - 子集 → 在现有节点中增加细分章节
     - 超集 → 不创建，现有节点已覆盖
     - 同义 → 合并到现有节点，用别名标记
4. 确认命名符合规范
5. 在本索引中登记新节点
6. 创建文件
```

---

*索引维护：每次新增/删除节点后，必须更新本文件*
*索引位置：D:/stock/Analysis/knowledgeGraph/_meta/node_index.md*
*维护责任人：预期差分析 Agent*
*路径迁移时间：2026-06-24（从 D:/stock/knowledgeGraph/ 迁移至此）*
