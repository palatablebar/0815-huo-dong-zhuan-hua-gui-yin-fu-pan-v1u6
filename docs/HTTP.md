# 阶段接口

`POST /api/stages/<stage>` 接收 `multipart/form-data`。字段 `sample=dirty`、`sample=clean` 或 `file=<CSV>` 三选一。阶段为 `intake`、`prepare`、`calculate`、`policy`、`balance`。预览不入库。

`POST /api/runs` 接收同样的输入，执行全批并返回运行报告。`GET /api/runs` 返回最近 50 批。`GET /api/runs/<id>` 查询一批和当前复核状态。

`PATCH /api/runs/<id>` 接收 `revision`、`status` 和 `note`。状态使用 `APPROVED` 或 `HELD`。冲突返回 409，客户端读取新版本后重试。

`GET /api/runs/<id>/evidence` 下载内含运行清单、行号隔离、业务证据和复核信息的 JSON。

## 实验放量判定

`POST /api/experiments` 接收 `multipart/form-data`：`sample=ready`、`sample=risk` 或 `file=<CSV>` 三选一。
可选 `as_of=<整数>` 指定报告截止日；可选 `batch=<id>` 表示并入已有批次（源数据更新/退款晚到），
此时只重算受影响组，其余组沿用上一版。相同输入重跑命中同一批次，不新增判定。

`GET /api/experiments` 返回最近 50 个判定批次。`GET /api/experiments/<id>` 返回当前判定、
完整版本链 `versions` 和审计事件 `events`。

`POST /api/experiments/<id>/publish` 接收 JSON `{"note": "..."}`（3–200 字），发布不可发布的批返回 409。

`POST /api/experiments/<id>/rollback` 原子回滚到上一版；无历史版本返回 409。

`GET /api/experiments/<id>/evidence` 下载 `experiment-evidence/1` 证据包，含所有权版本的完整报告。
