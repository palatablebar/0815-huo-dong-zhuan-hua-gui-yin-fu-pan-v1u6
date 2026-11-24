# 活动转化归因复盘规则登记

- 规模：中型

## 功能模块

| 模块 | 动作 | 接口 | 核心文件 | 测试 |
|---|---|---|---|---|
| M1 样例采信 | 预览并定位坏行 | `POST /api/stages/intake` | `app/intake/service.py` | `tests/test_intake.py` |
| M2 触点筛选 | 检查领域约束 | `POST /api/stages/prepare` | `app/modules/prepare.py` | `tests/test_prepare.py` |
| M3 归因选择 | 查看业务计算结果 | `POST /api/stages/calculate` | `app/modules/calculate.py` | `tests/test_calculate.py` |
| M4 归因对账 | 查看签收判定 | `POST /api/stages/policy` | `app/modules/policy.py` | `tests/test_policy.py` |
| M5 运行对账 | 对照输入、采信和隔离行 | `POST /api/stages/balance` | `app/modules/reconcile.py` | `tests/test_reconcile.py` |
| M6 批次复核 | 执行批次并签发或暂缓 | `POST /api/runs、PATCH /api/runs/<id>` | `app/review/service.py` | `tests/test_review.py` |
| M7 证据交付 | 下载复核清单 | `GET /api/runs/<id>/evidence` | `app/evidence/render.py` | `tests/test_evidence.py` |
| M8 实验采信 | 记录键去重、来源唯一、跨组重叠 | `POST /api/experiments` | `app/experiment/intake.py` | `tests/test_experiment.py` |
| M9 放量判定 | 成熟度、同周期对照、退款净额增量 | `app/experiment/decide.py` | `app/experiment/decide.py` | `tests/test_experiment.py` |
| M10 版本账本 | 晚到重算、旧版留存、原子回滚、幂等重跑 | `POST /api/experiments/<id>/rollback` | `app/experiment/store.py` | `tests/test_experiment_lifecycle.py` |
| M11 判定单接口 | 发布、回滚、证据下载 | `POST /api/experiments/<id>/publish` | `app/api.py` | `tests/test_experiment_http.py` |

## 输入陷阱

| 编号 | 规则 | 处理 | 测试 |
|---|---|---|---|
| TRAP-02 | 去除 BOM | `app/intake/reader.py` | `tests/test_intake.py::test_bom_preserves_identifier` |
| TRAP-03 | 按逻辑记录读取引号内换行 | `app/intake/reader.py` | `tests/test_intake.py::test_quoted_newline_is_one_logical_record` |
| TRAP-04 | 重复表头计入忽略行 | `app/intake/service.py` | `tests/test_intake.py::test_repeated_header_is_counted` |
| TRAP-05 | 异常列数隔离 | `app/intake/schema.py` | `tests/test_intake.py::test_extra_column_is_isolated` |
| TRAP-06 | 归一化全角数字和千分位 | `app/intake/numeric.py` | `tests/test_intake.py::test_full_width_and_grouping_are_canonical` |
| TRAP-07 | 空值行隔离 | `app/intake/numeric.py` | `tests/test_intake.py::test_sentinel_keeps_row_out_of_total` |
| TRAP-08 | 记录键保留前导零 | `app/intake/schema.py` | `tests/test_intake.py::test_bom_preserves_identifier` |
| TRAP-14 | 冲突版本都进入隔离 | `app/intake/resolve.py` | `tests/test_intake.py::test_duplicate_conflict_removes_both_copies` |
| TRAP-16 | 引号未闭合时拒收文件 | `app/intake/reader.py` | `tests/test_intake.py::test_unclosed_quote_invalidates_source` |
| TRAP-18 | 区分空文件、全空白和仅表头 | `app/intake/reader.py` | `tests/test_intake.py::test_empty_states_have_distinct_causes` |
| TRAP-26 | 拒绝旧版本复核 | `app/review/store.py` | `tests/test_review.py::test_review_optimistic_lock` |
| TRAP-27 | 重复来源列出记录键并挡住整组 | `app/experiment/intake.py` | `tests/test_experiment.py::test_duplicate_source_within_group_lists_keys_and_blocks` |
| TRAP-28 | 跨组重叠挡住所有涉及组 | `app/experiment/intake.py` | `tests/test_experiment.py::test_cross_group_overlap_blocks_every_involved_group` |
| TRAP-29 | 未成熟但暂显优势不得放量 | `app/experiment/decide.py` | `tests/test_experiment.py::test_immature_advantage_does_not_ramp` |
| TRAP-30 | 同周期对照不一致判观察 | `app/experiment/decide.py` | `tests/test_experiment.py::test_period_mismatch_is_not_controlled` |
| TRAP-31 | 退款必须指向本组转化 | `app/experiment/intake.py` | `tests/test_experiment.py::test_unmatched_refund_blocks_group` |
| TRAP-32 | 晚到退款只重算受影响组 | `app/experiment/service.py` | `tests/test_experiment_lifecycle.py::test_late_refund_recomputes_only_affected_group` |
| TRAP-33 | 回滚原子切换且保留旧版 | `app/experiment/store.py` | `tests/test_experiment_lifecycle.py::test_rollback_switches_atomically` |
| TRAP-34 | 同批次重跑不新增判定 | `app/experiment/service.py` | `tests/test_experiment_lifecycle.py::test_rerun_same_batch_does_not_add_decision` |

## 领域反例

归因窗口含回溯起点，排除转化时刻。仅接受同意标志为 1 的触点。非直达优先，时间相同时按稳定记录键裁决。

逐组预期结论见 `tests/test_policy.py`，计算过程证据见 `tests/test_calculate.py`。

实验放量判定：未成熟或对照不完整的组一律观察，绝不按暂显优势提前放量；增量只用退款后净额。
逐组预期见 `tests/test_experiment.py`，版本与回滚见 `tests/test_experiment_lifecycle.py`。
