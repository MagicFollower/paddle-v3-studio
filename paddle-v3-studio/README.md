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
run.cmd                    :: FastAPI 同源直出 dist 与 /api，默认 http://127.0.0.1:8390
..\contract-source\run.cmd :: 合同数据源 http://127.0.0.1:8081（合同校验功能需要）
```

浏览器开 **http://127.0.0.1:8390/**。端口被占自动后移（8390–8430），实际端口写
`data/.port`（vite dev 代理读它）。开发回路：`run.cmd` + `npm run dev`（5175）。

## 样例与判据

```bat
.venv\Scripts\python.exe scripts\make_fixtures.py   :: 生成三份样例合同 docx+pdf（WPS COM）
.venv\Scripts\python.exe scripts\check_studio.py    :: 端到端判据（自起后端，真上传真推理真校验）
```

三份样例对应三种校验结局：

| fixture | 合同号 | 预期结局 |
|---|---|---|
| sample-HT-2026-001.docx/pdf | HT-2026-001 | matched（与数据源逐行一致） |
| sample-HT-2026-002-bad.docx | HT-2026-002 | mismatch（硒鼓数量 25≠20、金额不符） |
| sample-HT-2026-999.docx | HT-2026-999 | not_found（数据源无此合同号） |

## 接口契约（后端 server/app.py）

| 方法 路径 | 作用 |
|---|---|
| `GET /api/health` / `/api/overview` | 探活 / 计数 |
| `GET /api/model/status` / `POST /api/model/reprobe` | 设备+模型就位状态 / 重新探测 |
| `GET /api/schema` / `GET|POST /api/config` / `POST /api/config/validate` | schema 驱动配置 |
| `GET|POST /api/documents` | 图片列表 / 上传（文件头校验，自动起任务） |
| `GET /api/documents/:id` `/image` `/result` `/raw` | 明细 / 图片字节 / 归一化结果 / 原始 JSON |
| `DELETE /api/documents/:id` / `POST .../favorite` | 删除（连带产物）/ 收藏 |
| `POST /api/parse` / `GET /api/jobs?refId=` / `GET /api/jobs/:id` | 起任务 / 任务列表 / 明细（stagePath 真实） |
| `GET|POST /api/contracts` / `POST /api/contracts/upload` | 合同条目 / 上传 docx/pdf |
| `GET /api/contracts/:id/result` / `/pages/:n/image` | 解析产物 / 页图字节 |
| `POST /api/contracts/:id/parse` / `/reverify` | 重新解析 / 只重跑校验 |
| `GET /api/source/status` | Spring Boot 数据源探活 |

数据源契约（contract-source）：`GET /api/health`、`GET /api/contracts`、
`GET /api/contracts/{no}` → `{contract, items[]}`，不存在回 404。

## 目录

```
server/app.py            FastAPI 主程序（同源直出 dist，端口回退写 data/.port）
server/pipeline.py       PP-StructureV3 封装：离线模型目录、缩放还原、结果归一化
server/device.py         GPU 优先探测 + 真张量自检 + 降级留痕
server/config.py         data/config.json 默认值唯一来源 + schema + 交叉约束
server/store.py          上传件/产物/合同条目落盘（只碰 data/）
server/jobs.py           单工作线程任务引擎（图片三阶段 / 合同五阶段）
server/contract.py       WPS COM 转 PDF、pypdfium2 逐页转图、合同号正则、表格 HTML→条目
server/verify.py         对照数据源逐行校验（品名相似度+数量/单价/金额容差）
src/                     Vue3 前端（App + 三视图 + PageViewer 覆盖层）
scripts/setup.cmd        一次性安装（GPU 轮子失败自动 CPU）+ 预下载模型
scripts/setup_models.py  模型预下载与就位校验（落到 ../../MODEL-V3，需 venv）
scripts/download_models.py 双击即用离线模型下载器（纯标准库，已存在则跳过）
scripts/make_fixtures.py 样例合同生成（docx→WPS COM→pdf）
scripts/check_studio.py  端到端判据（退出码=失败条数）
scripts/check_contract_no.py 合同号七开关判据（17 条，--selftest 自证）
scripts/check_paths.py   相对路径合规判据（扫硬编码绝对路径）
doc/                     离线模型使用清单 + 项目与模型存放位置规范
../../MODEL-V3/          ASCII 模型库（运行时唯一模型来源，中文路径不可用）
data/                    上传件、产物、合同条目、配置、设备状态（运行时写盘区）
fixtures/                样例合同与真图
```

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