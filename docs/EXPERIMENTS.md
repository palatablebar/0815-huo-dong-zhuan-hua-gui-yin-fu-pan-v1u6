# 实验放量判定单

增长团队按日看提升，财务只在**同周期对照完整**且**退款后净额齐备**时承认增量。
本判定单把这套口径固化为可复核、可发布、可回滚的批次。

## 判定口径

对每个活动组（`group`）分别判定，处理臂 `treatment` 对照 `control`：

1. **样本成熟**：组内每笔转化都经过完整退款观察窗（`MATURITY_DAYS`，默认 7 天），
   即 `day + 7 <= as_of`。未成熟组一律 `OBSERVE`，即使暂显优势也不得放量。
2. **对照匹配**：同组两臂都必须存在，且两臂的转化日集合完全一致。缺臂或周期不一致
   均为对照不完整，判 `OBSERVE`。
3. **净额齐备**：增量按扣除退款后的净额计算：`net = gross - refund`，
   `lift = net(treatment) - net(control)`。
4. **决策**：三项门槛都满足后按 `lift` 正负判定：

| 情形 | 决策 | 含义 |
|---|---|---|
| `lift > 0` 且门槛全过 | `CONTINUE` | 继续放量 |
| `lift < 0` 且门槛全过 | `ROLLBACK` | 回滚 |
| `lift = 0` 或任一门槛未过 | `OBSERVE` | 继续观察，不得放量 |
| 出现完整性阻断 | `BLOCKED` | 禁止发布 |

`provisional_advantage` 标记「未成熟但暂显优势」，这类组 `ramp_allowed` 恒为 `false`。

## 记录唯一性

- 记录键 `record` 全局唯一：完全一致的重放只保留首条（`DUPLICATE_REPLAY`），
  冲突副本两边全部隔离（`DUPLICATE_CONFLICT`）。
- 来源键 `source` 是转化的业务唯一键：同一组内重复计入 `DUPLICATE_SOURCE`，
  跨组出现计入 `CROSS_GROUP_OVERLAP`。两者都会列出**原始记录键**并把涉及的
  活动组整组置为 `BLOCKED`，从而挡住整批发布。
- 退款必须指向本组已采信转化（`UNMATCHED_REFUND`），金额不得超过毛额
  （`REFUND_EXCEEDS_GROSS`），实验臂必须一致（`REFUND_ARM_MISMATCH`）。

## 批次发布与回滚

- **发布**要求整批 `publishable`：行数守恒、无隔离行、无完整性问题、无 `BLOCKED` 组。
  发布后不可再次发布。
- **晚到重算**：给 `POST /api/experiments` 传 `batch=<id>` 即视为同一报告批次的
  源数据更新/退款晚到。系统比较各组内容指纹，**只重算受影响的活动组**，
  其余组沿用上一版判定；截止日沿用首版，补录旧数据不会后移成熟度时钟。
- **旧版证据**：每个修订版本写入不可变证据链（`experiment_decisions`），
  回滚不删除任何版本。
- **原子回滚**：`POST /api/experiments/<id>/rollback` 在单事务内把生效指针切回上一版；
  任何失败整体回退，旧版判定与全部证据保持原样，不丢记录。
- **重跑幂等**：同一输入指纹 + 规则版本命中同一批次，重跑不新增判定版本；
  内容无变化的更新也视为无操作。

## 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/api/experiments` | 生成判定单；`sample=ready/risk`、`file=`、`batch=`、`as_of=`、`affected=` |
| `GET` | `/api/experiments` | 最近 50 个判定批次 |
| `GET` | `/api/experiments/<id>` | 当前判定 + 版本链 + 审计事件 |
| `POST` | `/api/experiments/<id>/publish` | 发布，JSON `{"note": "..."}` |
| `POST` | `/api/experiments/<id>/rollback` | 原子回滚到上一版 |
| `GET` | `/api/experiments/<id>/evidence` | 下载含全部历史版本的证据包 |

页面入口为 <http://localhost:18309/experiments>。

## 输入字段

| 字段 | 说明 |
|---|---|
| `record` | 记录键，保留前导零 |
| `group` | 活动组 |
| `arm` | `treatment` 或 `control` |
| `kind` | `conversion` 或 `refund` |
| `day` | 事件日（非负整数） |
| `value_cents` | 金额（分） |
| `source` | 转化来源键，退款用它指向被退款的转化 |
| `note` | 说明，≤ 200 字 |

同一套读取规则（BOM、引号内换行、重复表头、全角数字、千分位、空值、行数上限）
与归因复盘共享 `app/intake`。
