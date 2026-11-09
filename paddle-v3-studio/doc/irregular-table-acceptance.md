# 不规则表格识别集成 · 校验验收归档

> 场景：合同号+明细同表、内容完整但行列极不规范。核心：精确区分表格规范性，动态决定是否调用 4B LLM。
> 模型：`Spark-X2.6-4B-Q4_K_M.gguf`（本地离线端点，GPU RTX 3080 Ti）· 验收日期：2026-11-09
> 原始数据：[`irregular-acceptance-results.json`](./irregular-acceptance-results.json)（`scripts/make_irregular_demo.py --run` 真跑产出）

## 1. 集成架构（无缝接入现有流水线）

合同流水线 `convert→predict→extract→llm_map→verify→persist` 的 extract 阶段内，对每个表格：

```
assess_regularity(html) 精确判别规范性
   ├─ regular=True（标准/合并表头/分节，有可识别列表头）→ 启发式 table_to_entries 精确解析（含多行表头/分类小计快修）
   └─ regular=False（转置/键值对/无表头）→ 4B LLM normalize_table 规范化为标准行列 HTML
        → 复用正规 table_to_entries(规范化HTML) 解析（method=llm-normalize）
        → 规范化解析不出明细时回退 understand_table 结构理解兜底（method=llm-table）
   → 统一输出同形状 entries（内部键+cells）→ llm_map 映射业务字段 → verify 匹配后端响应
```

- **规范化层（核心）**：LLM 只做结构重排（提示词约束「只 rearrange 现有值、不增删改、缺失补空」），把不规则表
  重排为标准行列 HTML；值由确定性 `table_to_entries` 提取，最大化复用正规解析（cells/colmap/快修）。
  规范化中间产物 `normalizedHtml` 随表格块持久化，供界面审计。`config.llm.normalize_prompt` 可配置/还原默认。
- 判别依据：列表头探测（品名类+数量/单价/金额类同行）、首列字段标签数（转置特征）、跨列标签分布（键值特征）、
  rowspan/colspan 计数。返回 `{regular, layout, reasons, merge_count, header_found}`。
- 每个表格块携带 `method`（heuristic/llm-normalize/llm-table）、`layout`、`regular`、`regularityReasons`、
  `normalizedHtml`（规范化路径），供界面差异化展示与追溯。
- 校验对「未识别到合计行」跳过总额比对（不误判不符），明细逐行比对仍硬判据。
- 已知限制：规范化重排丢失原始几何，rowBoxNorm 暂为 None（前端跳转回退估算）；坐标值回映可后续完善。

## 2. 界面流程提示与差异化展示

合同校验「校验详情·合同明细（表格区域提取）」：
- 顶部流程提示横幅：规则表格→启发式精确解析；不规则表格→4B LLM 规范化为标准行列→复用正规解析（规范化无效回退结构理解）。
- 每表标注：方法徽章（`启发式精确解析`绿 / `4B 规范化→复用解析`橙 / `4B 结构理解兜底`橙）+ 形态标签
  （标准表/合并表头/转置表/键值对表/无表头）+ 规则性标签（规则/不规则）。
- 不规则表差异化：虚线橙红边框+浅橙底+原因提示行；**规范化审计视图**：可折叠「查看 4B 规范化后的标准表格」，
  以纯文本二维表（DOMParser textContent，杜绝 XSS）渲染 normalizedHtml 中间产物，供人工审计 LLM 重排结果。
- 解析任务日志（解析队列/详情）逐表记录判定与抽取路径，可追溯。

## 3. 八个真实 PDF 案例验收（4B 真跑，全 matched）

合同号均为后端 contract-source 已存在（HT-2026-001/002/003），明细逐字对齐 data.sql；真上传→OCR→表格识别→
动态路由→映射→后端查询校验。

| 案例 | 合同号 | 构造形态 | 判别 layout | regular | 路由 method | 条目 | 校验 |
|---|---|---|---|---|---|---|---|
| demo-irregular-kv-003 | HT-2026-003 | 键值对（单项） | transposed | 否 | **4B 规范化→复用** | 1/1 | matched |
| demo-irregular-transposed-002 | HT-2026-002 | 转置（2 项） | transposed | 否 | **4B 规范化→复用** | 2/2 | matched |
| demo-irregular-merged-001 | HT-2026-001 | 多行合并表头+分类+小计 | merged-header | 是 | 启发式 | 3/3 | matched |
| demo-irregular-kvmulti-002 | HT-2026-002 | 多项键值对（并列） | key-value | 否 | **4B 规范化→复用** | 2/2 | matched |
| demo-irregular-transposed-001 | HT-2026-001 | 转置（3 项） | transposed | 否 | **4B 规范化→复用** | 3/3 | matched |
| demo-irregular-rowspan-001 | HT-2026-001 | rowspan 分类合并 | merged-header | 是 | 启发式 | 3/3 | matched |
| demo-irregular-nohtable-003 | HT-2026-003 | 合同号在表内+键值明细 | transposed | 否 | **4B 规范化→复用** | 1/1 | matched |
| demo-irregular-sectioned-002 | HT-2026-002 | 多分类+多小计 | merged-header | 是 | 启发式 | 2/2 | matched |

**验收结论：8/8 全部 matched（EXIT=0），`matchSource=mapped`。**
- 动态路由精确：5 例不规则→4B 规范化为标准行列→复用正规 table_to_entries 解析（method=llm-normalize），3 例规则→启发式精确解析，各自正确抽取并匹配后端。
- 说明：单项键值/表内合同号被分类器归为 transposed（首列标签集中），regular=False 路由正确（→LLM）；
  形态子标签为辅助展示，规范性二分（regular）与路由决策准确。

## 4. 回归与复现

- `scripts/check_studio.py`：81/81（含 C7 三结局不变）。
- `scripts/check_table_irregular.py`：4/4 fixable + `--selftest` SELFTEST_OK（6 类形态判据）。
- 真编 dist：vite 7.3.7，~4.6s。

```bat
:: 需后端 8390 + 数据源 8081 + 4B 端点 9931 在线（llm-server.cmd 默认 4B）
.venv\Scripts\python.exe scripts\make_irregular_demo.py --run --base http://127.0.0.1:8390
.venv\Scripts\python.exe scripts\check_table_irregular.py --selftest
.venv\Scripts\python.exe scripts\check_studio.py
```

## 5. 归档产物

- 真实 PDF/docx：`fixtures/llm-demo/demo-irregular-*`（8 例）。
- 验收原始数据：`doc/irregular-acceptance-results.json`。
- 本报告：`doc/irregular-table-acceptance.md`。