# LLM 表格明细字段映射阶段 · 完整分析报告

> 阶段：`llm_map`（合同流水线「提取」之后、「对照数据源校验」之前）
> 模型：`Spark-X2.6-1.7B-Q4_K_M.gguf`（本地离线，llama.cpp `llama.exe serve`）
> 实测日期：2026-11-09 · 设备：NVIDIA GeForce RTX 3080 Ti（12 GB，CUDA0，`-ngl 99`）
> 原始数据：[`llm-benchmark-results.json`](./llm-benchmark-results.json)（由 `scripts/llm_benchmark.py` 真跑产出）

---

## 1. 阶段定位与数据流

合同解析流水线现为六阶段，`llm_map` 在调用后端合同查询接口（校验）**之前**完成转换：

```
convert → predict → extract → llm_map → verify → persist
 转图      逐页OCR    合同号+明细   LLM字段映射   对照后端查询   落盘
```

- **输入**：上一步 `extracted` json（含中文表头 `headers`、每条明细的 `cells`「中文表头→原值」、`rowBoxNorm` 行坐标）。
- **输出**：`mapped` json，键名为**真实业务字段名**，与后端合同查询接口逐字对齐：
  - 查询参数：`contractNo`（即 `mapped.contractNo`，用于 `GET /api/contracts/{contractNo}`）。
  - 响应参数 `items[]`：`sortOrder / itemName / spec / unit / quantity / unitPrice / amount`。
- **校验消费**：`verify` 优先用 `mapped` 的业务字段匹配后端响应（`report.matchSource=mapped`），
  文本值解析为数后按容差比对；映射跳过时回退 `extracted` 内部键，保证流水线始终可校验。

职责分离：**LLM 只做表头识别**（varied 中文表头 → 业务字段，小输出），**值的键名重写由
`fieldmap.transform` 确定性完成**——值原样 trim 保留，跨页 200+ 明细不丢行、不改数、可复现。

## 2. 接入方式：API 端点客户端 + 手动启动 + 解析前门控

- **纯 API 端点客户端**：后端 `server/llm.py` 以 OpenAI 兼容客户端方式调用 `config.llm.base_url`
  （默认本地 `http://127.0.0.1:9931`）+ `model`（默认 `spark-x2.6`）+ 可选 `api_key`，**不自行拉起模型**。
  可接任意远程/第三方端点。`chat` 带 `enable_thinking=false`，端点不接受（400）时自动去掉重试。
- **项目启动不启动 LLM**：本地模型由用户**双击 `llm-server.cmd` 手动启动**（前台 `llama.exe serve`，
  脚本侧 `--list-devices` 探测 GPU、无则 `-ngl 0` 降级 CPU；**关窗即终止并释放 GPU/显存**，全英文输出）。
- **解析前全模型硬门控**：`jobs.preflight_models` 同步检测四项 Paddle（本地就位）+ LLM（启用时端点可达
  且暴露所配模型）；任一必需模型不可用 → 手动解析回 HTTP 409、上传自动解析不起任务并回 `preflightError`。
  LLM 默认启用，故未手动起模型时解析被拒并提示。
- **优雅跳过**：`llm.enabled=false` 不门控 LLM；解析中途端点失效时 `mapped.status=skipped` 留痕，校验回退内部键。
- 实测设备：NVIDIA GeForce RTX 3080 Ti（CUDA0，`-ngl 99`，由 `llm-server.cmd`/测试助手探测）。

## 3. 多对一映射（多个中文字段 → 同一英文字段）

为增强不同合同表头的识别覆盖与转换精准性，支持多对一：

| 机制 | 说明 |
|---|---|
| 别名归并 | 一个英文字段挂多个中文别名（`itemName ← 品名/物料名称/货物名称/产品名称…`）；导入重复 `field` 行自动归并别名，不再报「重复」。 |
| 扁平配对导入 | 兼容 `{mappings:[{from:中文,to:英文}]}`，多行指向同一英文自动 grouping（界面与后端一致）。 |
| 取值合并 | 同一表多列命中同一字段时**非空优先**合并；若出现不同非空值，保留首个并把冲突留痕 `_conflicts`，避免静默覆盖丢值。 |
| LLM 提示强化 | 系统提示明确「多个同义中文表头可映射到同一英文字段，逐表头独立判断最匹配字段」。 |
| 确定性兜底 | 别名匹配精确相等优先、其次包含关系取最长命中（避免「品名规格」抢走「规格」）；LLM 未命中的表头由兜底补齐。 |

判据 E13–E16 覆盖：扁平配对归并、重复行归并、多列非空优先合并、冲突留痕。

## 4. 真实准确率与耗时实测（Part A）

真起本地 LLM，对 6 组 varied 表头测「表头→业务字段」命中率与单次耗时（含多对一/部分缺失/OCR 噪声）：

| 组别 | 实际表头（节选） | 命中率 | 单次耗时 |
|---|---|---|---|
| 标准表头 | 序号/品名/规格型号/数量/单价(元)/金额(元) | 7/7 = 100% | 359.5 ms |
| 物料表头 | 项次/物料名称/计量单位/采购数量/含税单价/含税金额 | 7/7 = 100% | 243.7 ms |
| 货物表头 | 行号/货物名称/型号/数目/单价/总价 | 7/7 = 100% | 222.3 ms |
| 多对一同义列 | 品名 + 产品名称 同列 → 均 itemName | 4/4 = 100% | 153.3 ms |
| 部分缺失表头 | 品名/数量/金额（缺规格/单位/单价） | 3/3 = 100% | 111.3 ms |
| OCR 空格噪声 | 品 名/数 量/单 价/金 额 | 4/4 = 100% | 178.0 ms |

- **总体准确率 100%（32/32 表头）**；服务冷启动 **1534 ms**；单次识别 **111–360 ms**。
- 采样 token 用量：prompt 323（其中缓存命中 142）/ completion 41 / total 364 —— 表头识别是轻量任务。
- 说明：准确率是「LLM 识别 + 别名兜底」合并后的系统命中率（流水线实际所用）；OCR 空格噪声组由兜底归一化保障。

## 5. 真实合同 · 跨页明细 · 部分存在部分不存在（Part B）

构造真实场景 PDF（`scripts/make_crosspage_demo.py`）：合同号 **HT-2026-001（后端 data.sql 已存在，3 条明细）**，
明细表用 varied 表头（物料名称/计量单位/采购数量/含税单价/含税金额），**33 行 = 后端真实 3 行 + 数据源没有的 30 行**，
表格自然跨 2 页（续页无表头）。真上传 → OCR → LLM 映射 → 后端查询校验：

| 维度 | 实测结果 |
|---|---|
| 页数 / 阶段路径 | 2 页；`convert→predict→extract→llm_map→verify→persist` |
| 跨页提取 | 表格块 2（页 1、页 2），明细 **33 条**（页 1 = 19，页 2 = 14），续页沿用上一页列映射 |
| LLM 映射 | `status=ok`，`engine=spark-x2.6`（API 端点），33 条；表头 `物料名称→itemName / 采购数量→quantity / 含税单价→unitPrice / 含税金额→amount …` |
| 校验匹配源 | `matchSource=mapped`（用转换后的业务字段匹配后端响应） |
| **部分存在** | `itemComparison` 33 行：**matched 3 行**（后端真实存在的联想笔记本/惠普打印机/得力复印纸）+ **数据源无此行 30 行**（OCR 多余行） |
| 校验结局 | `mismatch`（行数 33≠3、总额 147491≠87986 两条不符；合同号命中、跨页一致、明细提取三条通过） |
| 耗时 | 端到端 **31.06 s**；`llm_map` 阶段 **2.146 s**；任务总耗时 30.75 s |

结论：跨页明细被全量提取并精确映射到后端字段；与后端「部分存在部分不存在」被如实区分
（3 行匹配、30 行数据源无），校验不掩盖差异。端到端耗时主要由逐页 OCR 推理占据，LLM 映射阶段仅 ~2.1 s。

## 6. 三个不同表头合同 PDF 真实调用（`scripts/make_llm_demo.py --run`）

| 案例 | 合同号 | OCR 表头风格 | 转换 → 后端字段 | 校验 |
|---|---|---|---|---|
| A | HT-2026-001 | 序号/品名/规格型号/单价(元)/金额(元) | sortOrder/itemName/spec/unitPrice/amount | matched |
| B | HT-2026-002 | 项次/物料名称/计量单位/采购数量/含税单价/含税金额 | 同上（varied 自动识别） | matched |
| C | HT-2026-003 | 行号/货物名称/型号/数目/单价/总价 | 同上 | matched |

三例均 `matchSource=mapped`、`llm_map` 在 `verify` 前，汇总 `ALL_MATCHED`。

## 7. 耗时结构小结

- 冷启动 llama serve（GPU 加载 1.7B Q4）：~1.5 s（一次性，服务复用后摊薄）。
- 单次表头识别：~0.1–0.36 s（completion ~41 tokens，prompt 缓存可命中）。
- 合同 `llm_map` 阶段（含启动/复用 + 识别 + 确定性转换）：~2.1 s。
- 端到端合同解析：~31 s（2 页），瓶颈在逐页 PP-StructureV3 OCR，LLM 映射占比 < 7%。
- CPU 降级由 `llm-server.cmd` 侧探测（无 GPU 时 `-ngl 0`），端点模式后端不感知设备；CPU 可跑通，耗时高于 GPU。

## 8. 边界与已知限制（照实说）

- **模型规模**：1.7B Q4 只做表头识别（结构化小输出）胜任；不用于逐行重写整表（避免漏行/改值/幻觉）。
- **OCR 噪声**：识别值可能含空格（如「笔记 本」），品名匹配靠相似度（包含/Jaccard）容错；表头空格由别名归一化兜底。
- **多对一冲突**：同表多列同字段且值不同时保留首个非空并 `_conflicts` 留痕，需人工复核取舍。
- **部分匹配语义**：数据源无的 OCR 行记「数据源无此明细行」，行数/总额不符判 mismatch，不静默吞差异。
- **降级与跳过**：无 GPU 降 CPU；模型/bin 缺失或关闭则 `skipped` 留痕、校验回退内部键，不阻断主流程。
- **参考后端**：contract-source 仅演示契约（H2 固定 seed），非生产服务；只绑 127.0.0.1。

## 9. 验证汇总

- 端到端判据 `scripts/check_studio.py`：**78/78 通过**（含 C5c cells、E1–E16 映射/多对一、E17/E17b/E18 全模型门控
  在线放行与端点不可达回 409、E10–E12 真 LLM 经端点映射匹配后端）。
- 真编 dist：vite 7.3.7，~4.6 s，js ~1.10 MB（gzip ~359 kB）。
- 浏览器实测：字段映射编辑（多对一别名/导入）、设置 LLM 面板、合同「业务字段(LLM)」tab（跨页 33 条、后端字段列）、
  错误明细清单（30 行数据源无）、逐行对照红标与跳转，**零控制台报错**。
- 设备双路径：GPU（RTX 3080 Ti）与 CPU 降级均真跑通过。

## 10. 复现命令

```bash
# 准确率/耗时 + 跨页部分存在端到端（需后端 8390 + 数据源 8081 在线）
.venv\Scripts\python.exe scripts\llm_benchmark.py --base http://127.0.0.1:8390
# 三个不同表头合同 PDF 真实调用
.venv\Scripts\python.exe scripts\make_llm_demo.py --run
# 仅生成跨页+部分存在场景 PDF
.venv\Scripts\python.exe scripts\make_crosspage_demo.py
# 全套判据
.venv\Scripts\python.exe scripts\check_studio.py
```