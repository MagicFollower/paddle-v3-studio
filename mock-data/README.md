# 模拟数据备份（复测用）

本目录收集项目复测所需的全部模拟输入与数据库快照，**已纳入版本管理**（见根 `.gitignore`
的 `!mock-data/**` 例外）。均为虚构模拟数据，不含真实业务信息。

## 目录

| 子目录 | 内容 |
|---|---|
| `contracts/` | 模拟合同 docx + pdf（WPS COM 转换）。`sample-HT-2026-*` 为校验三结局样例（matched/mismatch/not_found）；`stress-STRESS-2026-*` 为 10+ 页压力样例 |
| `images/` | 图片解析样例 `upload-sample.png`（单行）、`dense-sample.png`（多框密排） |
| `database/` | `contractdb.mv.db`：contract-source 的 H2 文件库快照（合同主表 + 明细，种子数据） |

## 压力合同覆盖的边界

| 文件 | 页数 | 明细条数 | 合同号位置 | 编号形态 |
|---|---|---|---|---|
| stress-STRESS-2026-001 | 15 | 240 | 第 2 页（非首页） | 标签/值分行（多行） |
| stress-STRESS-2026-002 | 16 | 260 | 第 3 页（非首页） | 标签/值分行（多行） |
| stress-STRESS-2026-003 | 15 | 220 | 第 2 页 + 末页重复 | 多行 + 跨页一致性 |

明细表均 200+ 条且跨页，用于验证超长表格跨页提取与跨页合同号一致性校验。

## 复测方法

```bat
:: 合同/图片可直接上传到「文件条目」Tab，或经脚本生成器重生成：
.venv\Scripts\python.exe scripts\make_fixtures.py          :: sample 三结局样例
.venv\Scripts\python.exe scripts\make_stress_contracts.py  :: 10+ 页压力样例

:: 数据库快照恢复到 contract-source（先停服务）：
copy /Y mock-data\database\contractdb.mv.db contract-source\data\contractdb.mv.db
```

> 数据库恢复须在 contract-source 停止时进行（H2 运行时会锁文件）。