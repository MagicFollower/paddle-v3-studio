# 字段映射广度扩展 · 黑箱测试与二次优化归档

> 目标：扩充字段映射条目支持更多合同类型；10 份不同真实场景合同案例匹配不同字段映射；
> 在最新流程（规范性判别→规范化/启发式→LLM 映射→后端校验）上做黑箱测试，据结果二次优化并回归。
> 模型：`Spark-X2.6-4B-Q4_K_M.gguf`（本地离线端点，GPU）· 日期：2026-11-09
> 原始数据：[`field-mapping-test-results.json`](./field-mapping-test-results.json)（`scripts/check_field_mapping.py --run` 真跑）

## 1. 字段映射扩展

`fieldmap.DEFAULT_MAPPING` 由 7 字段扩至 **15 字段**：
- 核心 7（对齐后端响应）：sortOrder/itemName/spec/unit/quantity/unitPrice/amount，别名大幅丰富
  （设备名称/材料名称/货品名称/物料描述、技术规格/规格尺寸、订购数量/需求数量、净价/不含税单价、不含税金额/净价金额 等）。
- 扩展 8（支持更丰富合同）：taxRate(税率)/taxAmount(税额)/brand(品牌)/origin(产地)/manufacturer(制造商)/
  deliveryDate(交货期)/warranty(质保期)/remark(备注)。
- 校验只比对后端有的核心字段；扩展字段被抽取/映射/展示但不参与后端比对。多对一归并/扁平配对导入不变。

## 2. 十个真实场景案例（不同字段映射）

合同号均后端存在（HT-2026-001/002/003），核心明细对齐 data.sql；7 规则表（不同表头别名+扩展列）+ 3 不规则表。

| 案例 | 合同号 | 形态 | 考验的字段映射 | 路由 | 结果 |
|---|---|---|---|---|---|
| m01-standard-001 | HT-2026-001 | 规则 | 品名/规格型号/单价(元)/金额(元) | 启发式 | matched |
| m02-material-002 | HT-2026-002 | 规则 | 物料名称/计量单位/采购数量/含税单价/含税金额 | 启发式 | matched |
| m03-goods-003 | HT-2026-003 | 规则 | 货物名称/型号/数目/单价/总价 | 启发式 | matched |
| m04-tax-001 | HT-2026-001 | 规则(9列) | 设备名称/技术规格/订购数量/不含税单价/不含税金额 + **税率/税额** | 4B 规范化 | matched |
| m05-brand-002 | HT-2026-002 | 规则(9列) | 商品名称/型号规格/需求数量/净价/净价金额 + **品牌/产地** | 4B 规范化 | matched |
| m06-mfr-001 | HT-2026-001 | 规则(9列) | 产品名称/规格描述/单价（含税）/金额（含税） + **生产厂家/质保期** | 启发式 | matched |
| m07-delivery-002 | HT-2026-002 | 规则(9列) | 物料描述/规格尺寸/订单数量/单价(含税) + **交货期/备注** | 启发式 | matched |
| m08-kv-003 | HT-2026-003 | 不规则键值 | 核心字段（键值对） | 4B（规范化/兜底） | matched |
| m09-transposed-002 | HT-2026-002 | 不规则转置 | 核心字段（转置） | 4B（规范化/兜底） | matched |
| m10-merged-001 | HT-2026-001 | 不规则合并 | 核心字段（多行合并表头） | 启发式 | matched |

## 3. 黑箱测试 → 二次优化 → 回归

**首轮黑箱（8/10）**：m04/m05 失败——扩展字段（税率/税额、品牌/产地）丢失。
**根因定位**：① 宽表（9列）被 SLANeXt 识别后规范性判为 key-value，走规范化路径；
② 规范化提示词旧版只输出核心 7 列，**丢弃扩展列**；③ 运行时 `config.json` 残留旧 `normalize_prompt` 覆盖代码默认。
**二次优化**：
- `DEFAULT_NORMALIZE_PROMPT` 改为「保留表格所有原始列名（含扩展列），绝不丢弃任何原始列，只 rearrange 不增删改」。
- 重置运行时残留 `normalize_prompt`（留空回退代码最优默认）。
**回归（全绿）**：
- 字段映射黑箱 `check_field_mapping.py --run`：**10/10 matched**（扩展字段 taxRate/taxAmount/brand/origin/manufacturer/warranty/deliveryDate/remark 全部正确映射）。
- `check_studio.py`：**81/81**。
- `check_table_irregular.py`：**4/4** + `--selftest` SELFTEST_OK。

## 4. 复现

```bat
:: 需后端 8390 + 数据源 8081 + 4B 端点 9931 在线；映射用默认 15 字段（POST /api/field-mapping/reset）
.venv\Scripts\python.exe scripts\check_field_mapping.py --run --base http://127.0.0.1:8390
.venv\Scripts\python.exe scripts\check_studio.py
.venv\Scripts\python.exe scripts\check_table_irregular.py --selftest
```

## 5. 归档产物

- 真实 PDF/docx：`fixtures/field-mapping/m01..m10`（10 例）。
- 黑箱原始数据：`doc/field-mapping-test-results.json`。
- 本报告：`doc/field-mapping-test-report.md`。
- 经验：规范化提示词必须保留全部原始列（否则扩展字段丢失）；运行时配置残留会覆盖代码默认，验收前应 reset 映射/提示词到默认。