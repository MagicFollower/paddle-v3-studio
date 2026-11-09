# Paddle V3 版面分析与 OCR 工作台（paddle-v3-studio）

方案B 的新项目：**PaddleOCR 3.x 的 PP-StructureV3 全新 V3 流水线**
（PP-DocLayoutV3 版面检测 + PP-OCRv5 文本检测/识别 + SLANeXt 表格识别），
与隔壁 `paddleocr-vl-studio` 的 GGUF/llama.cpp 路线完全独立：这里有真正的
**版面类别标签、表格结构化、OCR 置信度**——这三样正是 GGUF 路线给不了的。

Vue 3 + Element Plus 前端（固定版本 vue 3.5.44 / element-plus 2.14.7 / vite 7.3.7 /
@vitejs/plugin-vue 6.0.10 / @element-plus/icons-vue 2.3.2）+ FastAPI 后端 + 项目内 `.venv`。

## 两个任务，一个工程

1. **图片解析**：上传图片 → 版面区域框（类别+score）+ OCR 文本框（置信度三档分色）
   + 表格 HTML；右栏块卡片 / OCR 文本 / JSON 三页签，框与卡片双向联动。
2. **合同校验**：上传合同 docx/pdf，**一个文件一个条目**；逐页转独立图片
   （PDF 用 pypdfium2；DOCX 经本机 WPS COM 转 PDF），每页跑 V3 流水线；
   标出**合同号区域与文本**、**明细表格区域与条目**，再对照
   `../contract-source`（Spring Boot Web 2.7.18 + H2）查询数据源逐行校验。

## 合同号识别开关（系统设置 · 合同校验）

合同号可能在文档中以单行或多行出现、并在多页重复。以下开关均可在界面配置
（`config.contract`，逻辑见 [`server/contract.py`](server/contract.py) `extract_contract_no`）：

| 开关 | 默认 | 作用 |
|---|---|---|
| `match_single_line` 单行匹配 | 开 | 标签与编号同行（`合同编号：HT-2026-001`） |
| `match_multi_line` 多行匹配 | 开 | 标签独占一行、编号在下一行；编号被折成两行也会拼接 |
| `cross_page_check` 跨页准确性校验 | 开 | 统计各页出现、判定一致性，按**多数投票**选定编号；不一致会在校验报告记一条不符 |
| `min_no_confidence` 置信度下限 | 0.6 | 候选行 OCR 置信度低于此值则丢弃，挡低质量误读 |
| `no_format_regex` 格式白名单 | 空 | 编号须 `fullmatch` 该正则才采纳（如 `^HT-\d{4}-\d{3}$`），空=不启用；挡发票号/附件号误命中 |
| `prefer_first_page` 首页优先 | 开 | 选定/平票时优先最早页命中（合同号通常在首页） |
| `normalize_confusables` 易混字符归一化 | 关 | 跨页比对与输出编号做 `O→0`、`I/l→1`，减少形近字导致的假"不一致"；可能掩盖真实差异，故默认关 |

判定结果落在产物的 `extracted.crossPage`（出现次数/页/不同编号/一致性/过滤计数），
合同详情页有专节展示；`scripts/check_contract_no.py` 以合成数据覆盖全部开关
（17 条，`--selftest` 注入缺陷自证会红）。

## 显示与配色（系统设置 · 显示与配色）

区域框选开关与配色统一在 `config.display`，图片解析与合同校验两视图共用
（[`src/display.js`](src/display.js) 响应式共享 + CSS 变量全局生效）：

| 开关 | 默认 | 作用 |
|---|---|---|
| `show_contract_no` 合同号区域框 | 开 | 合同页图标出合同号区域 |
| `show_contract_table` 合同明细表格框 | 开 | 合同页图标出明细表格区域 |
| `show_layout` 版面区域框 | 关 | 叠加版面检测区域框 |
| `show_ocr` OCR 文本框 | 关 | 叠加 OCR 文本框（三档着色） |

- 两视图顶部有**快捷开关**，切换即时生效并写回 `data/config.json`。
- 8 项**自定义配色**（合同号/明细表/版面/OCR 三档/校验一致/不符），默认即原配色方案；
  设置页每项带取色器与「还原」按钮，可**单独还原默认**；编辑即时预览，保存后全局生效。
- 设备「重新探测」自检前会 `paddle.disable_static()`，避免推理后静态图导致 `.numpy()`
  误报 GPU 降级；合同数据源「测试连接」给出成功/失败提示。

## 文件条目 Tab 与通用组件

默认首页「文件条目」是统一的上传文件查询台（图片 + 合同），上下布局：

- **上·查询区**（[`QueryBuilder.vue`](src/components/QueryBuilder.vue)）：上传时间范围、
  合同号模糊、文件类型、解析状态、校验结果（完全匹配/明细不符/合同号不存在/未识别号，
  多选）；右下角按钮**查询在左、重置在右**，**重置只清空条件、不触发重查询**。
- **上传按钮**：位于查询区与 Grid 之间、Grid 左上角，接受图片与合同 docx/pdf，按扩展名
  路由到对应上传接口，上传后自动解析并刷新 Grid。
- **下·内容区**（[`ContentGrid.vue`](src/components/ContentGrid.vue)）：文件名/扩展名/大小/
  页数/类型/**解析状态**/合同号/校验/上传时间，右侧固定栏「详情/删除」；详情跳到对应解析
  界面并**自动滚动定位**到左侧列表选中条目，删除需确认。默认每页 15，可切 10/15/30/50/100/200。

两个组件高可配置：

- `QueryBuilder` 字段类型支持 `text / number / select / multiselect / radio / checkbox /
  daterange / api-select / map-select`；`api-select` 调接口取 JSON 列表，按 `idKey`(value1)
  为值、`labelKey`(value2) 为显示；`map-select` 用固定 `{id:name}` Map。
- `ContentGrid` 列由 `columns` 配置（宽/对齐/formatter/插槽），`actions` 配置固定操作栏，
  `show-pagination` 开关控制分页器显隐（隐藏则不使用分页），`page-sizes` 可配；
  `pagination-mode` 双模式：`bottom`（默认，Grid 顶满页面下区域、分页器跟随屏幕底部）
  与 `inline`（分页器跟随当前数据量）。

后端 `GET /api/entries` 统一返回两类条目，支持 `q/dateFrom/dateTo/parsed/verify/type`
过滤 + `page/pageSize` 分页。`display.default_zoom`（默认 60）控制页图初始缩放；
解析/重新解析/重新校验/删除/上传等按钮在处理中统一置灰不可点。

## 模型清单（全部）

运行时共两类、五项模型，全部离线就位（安装阶段预下载，运行时零联网）：

| 模型 | 用途 | 存放 | 接入方式 |
|---|---|---|---|
| `PP-DocLayoutV3` | 版面检测（类别+score） | `../../MODEL-V3/official_models/` | Paddle 本地推理 |
| `PP-OCRv5_server_det` | 文本行检测（四点框） | 同上 | Paddle 本地推理 |
| `PP-OCRv5_server_rec` | 文本行识别（文字+置信度） | 同上 | Paddle 本地推理 |
| `SLANeXt_wired` | 有线表格结构识别（HTML） | 同上 | Paddle 本地推理（启用表格识别时） |
| `Spark-X2.6-1.7B-Q4_K_M.gguf` | LLM 表头→业务字段映射 | `../../MODEL-V3/llms/` | **OpenAI 兼容 API 端点**（默认本地 `http://127.0.0.1:9931`） |

- 前四项 Paddle 模型由 `server/pipeline.py` 加载，模型名/设备在系统设置「模型与设备」配置；
  目录缺失报 `MODEL_MISSING`。模型库必须在 **ASCII 路径**（见「离线纪律」）。
- LLM 以**客户端方式接入 API 端点**，后端不自行拉起模型；可用 `../../MODEL-V3/llms/Spark-X2.6-4B-Q4_K_M.gguf`
  换更大模型（改 `llm-server.cmd` 的 `MODEL` 与设置里的 `model` 别名），或接任意远程/第三方 OpenAI 兼容端点。

## LLM 字段映射（API 端点接入）

合同流水线在「提取」后、「对照数据源校验」**之前**新增 **llm_map** 阶段：输入上一步的 `extracted` json，
输出具有**真实业务字段名**键名的新 json（产物 `mapped`，合同详情页「业务字段(LLM)」tab 可视化）。
默认映射目标字段与后端合同查询接口逐字对齐——查询参数 `contractNo`（即 `mapped.contractNo`），
响应参数 `items[]` 的 `sortOrder/itemName/spec/unit/quantity/unitPrice/amount`。校验阶段优先用这份
转换后的 json 匹配后端响应（`report.matchSource=mapped`），映射跳过时回退内部键。

**接入与启动（关键变化）**：

- 后端是**纯 OpenAI 兼容 API 客户端**（[`server/llm.py`](server/llm.py)），`config.llm` 配置
  `base_url`（默认 `http://127.0.0.1:9931`）/ `model`（默认 `spark-x2.6`）/ `api_key`（可选 Bearer）/ `timeout`。
- **项目启动不拉起 LLM 服务**。本地模型由用户**双击 [`llm-server.cmd`](llm-server.cmd) 手动启动**：
  该脚本前台运行 `llama.exe serve`，自动探测 GPU（`--list-devices`，无则 `-ngl 0` 降级 CPU），
  **关闭 cmd 窗口即终止模型并释放 GPU/显存**；输出全英文。启动后在系统设置确认端点可达即可。
- 也可在系统设置「LLM 字段映射」分组填写**远程/第三方端点** + 模型名 + API Key，无需本地 gguf。
- 设置页提供**「检测 LLM 可用性」**（`POST /api/llm/check`，探 `/v1/models` 核对模型名，退回 `/health`）
  与**「模型可用性总览」**（`GET /api/models/availability`，含全部五项模型）。
- **前置提示词可配置**：`config.llm.system_prompt` 是 LLM 表头映射的 system prompt。代码内固化一份基于本工程
  流程的最优默认（`config.DEFAULT_SYSTEM_PROMPT`：锁定只做表头映射、多对一、仅选给定字段、未知置 null、
  OCR 噪声归一化、严格 JSON 输出）；设置页「LLM 字段映射」分组以多行文本编辑，可覆盖保存、可一键**还原默认**，
  留空则回退代码最优值。动态的目标字段别名块与实际表头由 `llm._build_prompt` 自动追加在 user 消息。

**职责分离与映射配置**：

- LLM 只把 varied 中文表头识别到配置的业务字段（小输出，方向归一化 + 别名兜底）；值的键名重写由
  [`server/fieldmap.py`](server/fieldmap.py) `transform` 确定性完成——值原样 trim 保留，200+ 明细不丢行不改值。
  每条明细提取阶段保留 `cells`（中文表头→原值）覆盖任意表头。
- **多对一**：一个英文字段挂多个中文别名（`itemName ← 品名/物料名称/货物名称…`）；导入兼容扁平配对
  `{mappings:[{from,to}]}` 自动归并；同表多列命中同一字段时非空优先合并、冲突留痕 `_conflicts`。
- 左侧「字段映射」页逐条编辑 `{英文缩写, 中文标签, 中文表头别名[]}`，支持导入/导出/复制 JSON、恢复默认；
  独立存于 `data/field_mapping.json`。
- **触发**：每次合同解析自动跑（端点不可用时优雅跳过并留痕）；也可在合同详情页点「LLM映射」对已解析合同
  单独重跑（`POST /api/contracts/:id/llm-map`）。

## 解析前全模型可用性门控

**任何解析（图片/合同，含上传自动解析）开始前，同步检测所有模型可用性，全部通过才放行，否则报错拒绝**
（[`server/jobs.py`](server/jobs.py) `preflight_models` / `require_models`）：

- 必需模型 = 四项 Paddle（本地目录就位）+ LLM（**仅当 `llm.enabled`** 时要求端点可达且暴露所配模型）。
- 任一必需模型不可用 → `ModelUnavailable`；手动解析端点回 **HTTP 409**「模型可用性未通过，禁止解析：…」，
  上传自动解析则不起任务并在响应回 `preflightError`。
- LLM 默认 `enabled=true` + 本地端点：**未手动启动 `llm-server.cmd` 时解析会被门控拒绝**，
  提示先启动模型或在设置关闭 LLM。设置页「模型可用性总览」实时显示各模型状态与门控结论。

## 离线纪律（与 MODEL/offline 同款）

- **安装阶段联网，运行时零联网**：`scripts\setup.cmd` 一次性装依赖并把流水线全部
  模型预下载进 **`../../MODEL-V3`**（ASCII 模型库）；运行时更新检查被禁用
  （`PADDLE_PDX_DISABLE_UPDATE_CHECK`），模型目录显式传入，缺模型直接报
  `MODEL_MISSING`，**不偷偷下载、不回落假数据**。
- **为什么模型库不在工程内**：Paddle 的 C++ 推理引擎在 Windows 上**读不了含中文的
  路径**（实测同一份模型，ASCII 路径加载成功、中文路径报
  `json.exception.parse_error.101 empty input`）。本工程在「方案B：版面分析与OCR」
  下，路径含中文，所以模型库放 ASCII 的 `OCR-ALONE/MODEL-V3`——与另一工程引用
  `../MODEL/offline` 的惯例一致。可用 `PADDLE_V3_MODEL_HOME` 指到别的 ASCII 目录。
- 合同数据源 H2 是**文件库**（`contract-source/data/contractdb`），种子数据在
  `data.sql`，重启不丢、不依赖外部数据库。
- 前后端只绑 `127.0.0.1`，写盘只碰 `data/`。

## GPU 优先，降级留痕

`server/device.py` 先查 CUDA 编译旗标与设备数，再**真做一次 GPU 张量运算**自检；
任何一步失败就降级 CPU，原因写进 `data/device.json` 并经 `/api/model/status`
暴露——系统设置页有黄色告警条，顶栏有 `CPU（GPU 降级）` 标签。
配置 `model.device = auto|gpu|cpu`；`gpu` 档不可用时同样降级并明说原因。

## 跑起来（顺序不能反）

```bat
scripts\setup.cmd          :: venv + GPU轮子(失败自动CPU) + paddleocr + 预下载模型（联网仅此一次）
build.cmd                  :: npm ci + vite build
run.cmd                    :: FastAPI 同源直出 dist 与 /api，默认 http://127.0.0.1:8390（不拉起 LLM）
..\contract-source\run.cmd :: 合同数据源 http://127.0.0.1:8081（合同校验功能需要）
llm-server.cmd             :: 手动启动本地 LLM（双击，前台运行；关闭窗口即停止释放）
```

浏览器开 **http://127.0.0.1:8390/**。端口被占自动后移（8390–8430），实际端口写
`data/.port`（vite dev 代理读它）。开发回路：`run.cmd` + `npm run dev`（5175）。

**LLM 生效流程**：`run.cmd` 起后端（默认不启动 LLM）→ 双击 `llm-server.cmd` 起本地模型（或设置远程端点）
→ 系统设置「检测所有模型」确认全部可用 → 解析时门控放行 → `llm_map` 经端点转换 → 校验匹配后端响应。
未启动 LLM 且 `llm.enabled=true` 时，解析被门控拒绝并提示；关闭 LLM 则解析不受其影响（`llm_map` 跳过）。

## 样例与判据

```bat
.venv\Scripts\python.exe scripts\make_fixtures.py        :: 生成三份样例合同 docx+pdf（WPS COM）
.venv\Scripts\python.exe scripts\check_studio.py         :: 端到端判据 81 条（自起后端+本地 LLM，真上传真推理真校验+门控）
.venv\Scripts\python.exe scripts\make_llm_demo.py --run  :: 3 份不同表头合同 PDF 真实调用（全 matched）
.venv\Scripts\python.exe scripts\make_crosspage_demo.py  :: 生成跨页+部分明细存在场景 PDF
.venv\Scripts\python.exe scripts\llm_benchmark.py        :: 真起 LLM 测准确率/耗时 + 跨页端到端（结果落 doc/）
```

三份样例对应三种校验结局：

| fixture | 合同号 | 预期结局 |
|---|---|---|
| sample-HT-2026-001.docx/pdf | HT-2026-001 | matched（与数据源逐行一致） |
| sample-HT-2026-002-bad.docx | HT-2026-002 | mismatch（硒鼓数量 25≠20、金额不符） |
| sample-HT-2026-999.docx | HT-2026-999 | not_found（数据源无此合同号） |

`check_studio.py` 覆盖：静态/契约（A）、图片真解析（B）、合同校验三结局（C，含 cells/跨页坐标）、
文件条目查询（D）、LLM 字段映射与多对一（E1–E16）、端点状态与全模型门控（E17/E17b/E18：在线放行、
端点不可达回 409）、前置提示词可配置/生效/留空回退默认（E19）、真 LLM 映射匹配后端响应（E10–E12，`matchSource=mapped`）。
LLM 相关判据由脚本经 `scripts/llm_local.py` 手动起本地模型（后端不自行拉起）。
实测准确率/耗时与跨页+部分存在场景见 [`doc/llm-stage-analysis.md`](doc/llm-stage-analysis.md)。

## 接口契约（后端 server/app.py）

| 方法 路径 | 作用 |
|---|---|
| `GET /api/health` / `/api/overview` | 探活 / 计数 |
| `GET /api/model/status` / `POST /api/model/reprobe` | 设备+模型就位状态 / 重新探测 |
| `GET /api/schema` / `GET|POST /api/config` / `POST /api/config/validate` | schema 驱动配置 |
| `GET|POST /api/documents` | 图片列表 / 上传（文件头校验，自动起任务） |
| `GET /api/documents/:id` `/image` `/result` `/raw` | 明细 / 图片字节 / 归一化结果 / 原始 JSON |
| `DELETE /api/documents/:id` / `POST .../favorite` | 删除（连带产物）/ 收藏 |
| `POST /api/parse` / `GET /api/jobs?refId=` / `GET /api/jobs/:id` | 起任务（前置全模型门控，不可用回 409）/ 任务列表 / 明细 |
| `GET|POST /api/contracts` / `POST /api/contracts/upload` | 合同条目 / 上传 docx/pdf（自动解析受门控） |
| `GET /api/contracts/:id/result` / `/pages/:n/image` | 解析产物 / 页图字节 |
| `POST /api/contracts/:id/parse` / `/reverify` | 重新解析（前置门控）/ 只重跑校验 |
| `POST /api/contracts/:id/llm-map` / `GET .../mapped` | 单独重跑 LLM 字段映射 / 读映射产物 |
| `GET|POST /api/field-mapping` / `POST .../validate` / `.../reset` | 中文表头→业务字段映射配置（存取/校验/恢复默认） |
| `GET /api/llm/status` / `POST /api/llm/check` | LLM 端点状态 / 检测端点可用性（不拉起模型） |
| `GET /api/models/availability` | 全模型可用性总览（解析前门控同源，ok=False 禁解析） |
| `GET /api/source/status` | Spring Boot 数据源探活 |

数据源契约（contract-source）：`GET /api/health`、`GET /api/contracts`、
`GET /api/contracts/{no}` → `{contract, items[]}`，不存在回 404。

## 目录结构（最新）

```
paddle-v3-studio/
├─ server/                  FastAPI 后端（只绑 127.0.0.1，写盘只碰 data/）
│  ├─ app.py                主程序：/api 路由 + 同源直出 dist + 端口回退写 data/.port
│  ├─ config.py             data/config.json 默认值唯一来源 + schema + 交叉约束（含 llm 端点配置）
│  ├─ pipeline.py           PP-StructureV3 封装：离线模型目录、缩放还原、归一化、model_availability
│  ├─ device.py             Paddle GPU 优先探测 + 真张量自检 + 降级留痕
│  ├─ jobs.py               单工作线程任务引擎 + 解析前全模型门控（preflight_models/require_models）
│  ├─ contract.py           WPS COM 转 PDF、pypdfium2 逐页转图、合同号正则、表格 HTML→条目（保留 cells）
│  ├─ llm.py                LLM 纯 API 端点客户端：availability/chat/recognize_headers/run_mapping（不拉起模型）
│  ├─ fieldmap.py           中文表头→业务字段映射配置（data/field_mapping.json）+ 多对一归并 + 确定性键名重写
│  ├─ verify.py             对照数据源逐行校验（优先用 mapped 业务字段匹配后端响应）
│  └─ store.py              上传件/产物/合同条目/review 落盘
├─ src/                     Vue3 + Element Plus 前端
│  ├─ App.vue               菜单/视图登记（文件条目/图片解析/合同校验/解析队列/字段映射/系统设置）
│  ├─ api.js                fetch 封装（含 llmCheck/modelsAvailability/fieldMapping）
│  ├─ display.js            显示开关与配色响应式共享 + CSS 变量
│  ├─ components/           QueryBuilder / ContentGrid / PageViewer（覆盖层+高亮+审核标记）
│  └─ views/                FilesView / ImageParse / ContractCheck / QueueView / FieldMapping / SettingsView
├─ scripts/
│  ├─ setup.cmd / setup_models.py / download_models.py   安装与离线模型预下载
│  ├─ make_fixtures.py      三份样例合同（matched/mismatch/not_found）
│  ├─ make_llm_demo.py      3 份不同表头合同 PDF 真实调用（--run，全 matched）
│  ├─ make_crosspage_demo.py 跨页+部分明细存在场景 PDF（HT-2026-001，33 行跨 2 页）
│  ├─ llm_local.py          测试专用本地 llama 拉起助手（生产由 llm-server.cmd 手动起）
│  ├─ llm_benchmark.py      真起 LLM 测准确率/耗时 + 跨页端到端（结果落 doc/）
│  ├─ check_studio.py       端到端判据 78 条（自起后端+本地 LLM，退出码=失败条数）
│  ├─ check_contract_no.py  合同号七开关判据（17 条，--selftest）
│  └─ check_paths.py        相对路径合规判据
├─ doc/                     llm-stage-analysis.md 阶段分析报告 + llm-benchmark-results.json 实测数据
├─ llm-server.cmd           双击手动起本地 LLM（前台，关窗即停释放，全英文输出）
├─ build.cmd / run.cmd      构建 / 起后端（不拉起 LLM）
├─ fixtures/                样例合同与真图（含 llm-demo/ 生成件）
├─ data/                    运行时写盘区（上传件/产物/合同/配置/设备状态/field_mapping，gitignore）
└─ dist/                    前端构建产物（gitignore）
../../MODEL-V3/             ASCII 模型库（official_models/ 四项 Paddle + llms/ gguf 与 bin，运行时唯一来源）
../contract-source/         Spring Boot 2.7.18 + H2 合同查询数据源（8081）
```

## 代码地图（按职责）

- **入口与路由**：`server/app.py` 暴露全部 `/api`，解析端点前置 `jobs.require_models` 门控；
  `src/App.vue` 登记六个视图，`src/api.js` 统一 fetch。
- **配置中枢**：`server/config.py` 是 `data/config.json` 默认值与 schema 的唯一来源；
  `llm` 分组＝端点客户端参数（base_url/model/api_key/timeout/enabled），`model` 分组＝Paddle 模型与设备。
- **解析流水线**：`jobs.py`（图片三阶段 / 合同六阶段 convert→predict→extract→llm_map→verify→persist，
  单工作线程串行 + FIFO 队列 + 协作取消）；`pipeline.py` 跑 PP-StructureV3；`contract.py` 转图与要素提取。
- **模型可用性门控**：`pipeline.model_availability`（Paddle 就位）+ `llm.availability`（端点可达+模型名）
  → `jobs.preflight_models` 汇总 → `require_models` 在 `start_image_job/start_contract_job` 前置拦截。
- **LLM 字段映射**：`llm.py` 经 API 端点识别表头（`recognize_headers`，方向归一化+别名兜底）；
  `fieldmap.py` 存映射配置（多对一归并）并 `transform` 确定性重写键名；产物 `mapped` 由 `verify.py` 优先消费。
- **校验**：`verify.py` 调 `contract-source` 查询接口，用 mapped 业务字段（itemName/quantity/unitPrice/amount）
  按容差逐行比对，`report.matchSource` 标明匹配源。
- **前端可视化**：`ContractCheck.vue` 右栏 tabs（校验详情/OCR文本/合同明细/错误明细清单/业务字段(LLM)），
  错误红标+点击跳转+初审/审核回填；`FieldMapping.vue` 映射编辑；`SettingsView.vue` 端点配置+模型可用性总览。
- **本地模型启动**：`llm-server.cmd`（用户手动，前台，关窗释放）；测试用 `scripts/llm_local.py` 拉起。

## 已知边界

- **模型库必须在 ASCII 路径**：Paddle C++ 引擎读不了中文路径（见上）。工程内
  `data/`、`fixtures/` 含中文无碍——那些由 Python/WPS 读写；只有送进 Paddle 推理
  引擎的模型目录受此限制。
- DOCX 转 PDF 依赖本机 **WPS Office**（COM `KWPS.Application`，回退 `Word.Application`）；
  没有 WPS/Word 的机器上 docx 合同会失败并如实报错，PDF 合同不受影响。
- 合同号提取靠正则（合同编号/合同号/编号/Contract No 等）+ 上节七个开关；非常规写法
  仍可能漏检，漏检时校验结局为 `no_number`，界面明示，不猜一个号。格式白名单与易混
  归一化需按实际合同模板调配，默认保守（白名单空、归一化关）。
- 明细对照的品名匹配是粗相似度（包含关系/Jaccard），只用于定位对应行；
  数量/单价/金额按容差（默认 0.01）硬比对。校验报告是辅助，不替代人工复核。
- 表格结构识别对无线表/复杂合并单元格的还原率未量化；`SLANeXt_wired` 针对有线表。
- 任务表在内存，重启后任务历史清空；文档、产物、合同条目都在盘上。
- **LLM 需手动启动**：后端不拉起模型；`llm.enabled=true`（默认）时未启动 `llm-server.cmd`（或端点不可达）
  解析会被门控拒绝。接远程端点时 `chat` 带 `chat_template_kwargs.enable_thinking=false`，端点若不接受（400）
  会自动去掉重试；模型名须与端点 `/v1/models` 暴露的一致，否则可用性检测判不可用。
- LLM 仅做表头识别（1.7B 小输出），不做逐行重写；OCR 值可能含空格噪声，品名匹配靠相似度容错，
  表头空格由别名归一化兜底。多对一冲突保留首个非空值并 `_conflicts` 留痕，需人工复核。