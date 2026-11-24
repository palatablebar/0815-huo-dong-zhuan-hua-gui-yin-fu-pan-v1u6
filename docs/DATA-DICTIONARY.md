# 字段与业务定义

输入编码 UTF-8，允许 BOM。首行必须匹配样例列顺序。记录键和业务组保留原始字符串。`kind` 允许 touch, conversion, expected。说明列 `note` 可以跨行，限制 200 字。

业务字段按 `minute`、`channel`、`consent`、`value_cents`、`lookback` 排列。数字接受非负整数、全角数字和完整千分位。空串、短横线、N/A、NULL 与未知为缺值。无关字段用 0 占位。

归因窗口含回溯起点，排除转化时刻。仅接受同意标志为 1 的触点。非直达优先，时间相同时按稳定记录键裁决。

`incoming.csv` 包含四个业务组，第二组提供不同边界，第三组触发业务拒收，第四组需要核对。另含重复表头、冲突记录、重复回放与错误列数。`ready.csv` 含可以签发的两个组。

## 实验判定字段

实验判定单独一套列顺序：`record`、`group`、`arm`、`kind`、`day`、`value_cents`、`source`、`note`。
`arm` 为 `treatment` 或 `control`；`kind` 为 `conversion` 或 `refund`；`day`、`value_cents` 为非负整数。
`source` 是转化的业务唯一键（必填、跨组不可重复）；退款用它指向被退款的转化，并须与本组实验臂一致。
`record`、`group` 保留原始字符串（含前导零）。

`experiment_ready.csv` 两个已成熟、同周期、净额为正的活动组，整批可发布。
`experiment_risk.csv` 覆盖：未成熟但暂显优势（观察）、负增量（回滚）、重复来源（整组阻断）、跨组重叠（两侧阻断）。
