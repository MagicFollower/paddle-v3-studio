# contract-source · 合同与合同明细查询数据源

Spring Boot Web **2.7.18**（Java 8）+ H2 文件库，为 `../paddle-v3-studio`
的合同校验提供对照数据。纯查询数据源：合同主表 + 明细表，种子数据幂等写入。

## 跑起来

```bat
build.cmd   :: mvn -DskipTests package（首次构建联网拉依赖，此后离线）
run.cmd     :: java -jar target\contract-source.jar → http://127.0.0.1:8081
```

H2 文件库落在 `data/contractdb.mv.db`，重启不丢。种子数据在
`src/main/resources/data.sql`（`MERGE INTO ... KEY` 幂等，重启不重复）。

## 接口

| 方法 路径 | 回包 |
|---|---|
| `GET /api/health` | `{ok, service, springBoot, contracts, items}` |
| `GET /api/contracts` | `{items:[{contractNo,title,partyA,partyB,signDate,totalAmount,status}]}` |
| `GET /api/contracts/{no}` | 200 `{contract:{...}, items:[{sortOrder,itemName,spec,unit,quantity,unitPrice,amount}]}`；不存在 404 `{error:"not_found"}` |

## 种子合同

| 合同号 | 标题 | 明细 | 总额 |
|---|---|---|---|
| HT-2026-001 | 办公设备采购合同 | ThinkPad T14 ×10 / 惠普打印机 ×4 / A4 纸 ×50 | 87986.00 |
| HT-2026-002 | IT 耗材采购合同 | 硒鼓 ×20 / 网线 ×10 | 15600.00 |
| HT-2026-003 | 年度维保服务合同 | 年度维保 ×1 | 36000.00 |

与 studio 的三份样例合同一一对应：001 全对、002 数量金额不符、999 不在库。

## 改数据

直接改 `data.sql` 重启即可（MERGE 幂等）；或启动后用 H2 SQL 客户端连
`jdbc:h2:file:./data/contractdb`（sa / 空密码）在线改，改完在 studio 点「重新校验」。