"""实验报告：逐组判定 + 整批发布门槛。

整批发布要求：
- 每一行都在输入、采信、隔离或忽略之间守恒；
- 没有任何隔离行、重复来源或跨组重叠；
- 每个活动组完整（两臂齐全、同周期、样本充足、已成熟）；
- 整批没有任何 ROLLBACK 组需要处置。
"""

from collections import Counter
from hashlib import sha256
from json import dumps

from app.config import EXPERIMENT_RULE_VERSION, MATURITY_DAYS, MIN_PER_ARM
from app.experiment.decide import BLOCKED, CONTINUE, OBSERVE, ROLLBACK, evaluate
from app.experiment.intake import inspect


def by_group(rows):
    groups = {}
    for row in sorted(rows, key=lambda r: (r["group"], r["record"])):
        groups.setdefault(row["group"], []).append(row)
    return sorted(groups.items())


def group_fingerprint(rows):
    canonical = [
        [row["record"], row["group"], row["arm"], row["kind"],
         row["day"], row["value_cents"], row["source"]]
        for row in rows
    ]
    return sha256(dumps(canonical, separators=(",", ":")).encode()).hexdigest()


def observed_day(rows):
    days = [r["day"] for r in rows]
    return max(days) if days else 0


def summarize(intake, groups, day, as_of_source="data"):
    """由采信结果和逐组判定汇总整批门槛与判定。"""
    accounted = (
        intake["accepted"] + intake["rejected"] + intake["blank"] + intake["repeated"]
    )
    observed = sum(len(item["records"]) for item in groups)
    status = Counter(item["decision"] for item in groups)
    blocking = sorted(
        item["group"] for item in groups
        if not item["publishable"] or not item["ramp_allowed"]
    )
    counts = {
        "input": intake["input"],
        "accepted": intake["accepted"],
        "isolated": intake["rejected"],
        "ignored": intake["blank"] + intake["repeated"],
        "accounted": accounted,
        "observed": observed,
        "groups": len(groups),
        "continue": status.get(CONTINUE, 0),
        "observe": status.get(OBSERVE, 0),
        "rollback": status.get(ROLLBACK, 0),
        "blocked": status.get(BLOCKED, 0),
    }
    balanced = accounted == intake["input"] and observed == intake["accepted"]
    blocked = status.get(BLOCKED, 0)
    publishable = (
        balanced
        and intake["rejected"] == 0
        and not intake["issues"]
        and bool(groups)
        and blocked == 0
    )
    releasable = publishable and all(item["ramp_allowed"] for item in groups)
    return {
        "as_of_day": day,
        "as_of_source": as_of_source,
        "policy": {"maturity_days": MATURITY_DAYS, "min_per_arm": MIN_PER_ARM},
        "intake": {k: v for k, v in intake.items() if k != "rows"},
        "groups": groups,
        "decision": _batch_decision(groups, balanced, publishable, releasable),        "balance": {
            **counts,
            "balanced": balanced,
            "publishable": publishable,
            "blocking_groups": blocking,
            "releasable": releasable,
        },
    }


def report(data, as_of=None):
    """构建报告。`as_of` 缺省时取数据中观察到的最后一天。"""
    intake = inspect(data)
    rows = intake["rows"]
    day = observed_day(rows) if as_of is None else as_of

    groups = []
    for group, members in by_group(rows):
        item = evaluate(group, members, intake["issues"].get(group, []), day)
        item["source_fingerprint"] = group_fingerprint(members)
        groups.append(item)

    # 只有隔离行、没有采信行的活动组也必须出现，避免被静默丢弃。
    known = {item["group"] for item in groups}
    for group, issues in intake["issues"].items():
        if group not in known:
            item = evaluate(group, [], issues, day)
            item["source_fingerprint"] = group_fingerprint([])
            groups.append(item)
    groups.sort(key=lambda item: item["group"])

    return summarize(intake, groups, day, "data" if as_of is None else "caller")


def _batch_decision(groups, balanced, publishable, releasable):
    """整批判定：优先级 BLOCKED > ROLLBACK > OBSERVE > CONTINUE。"""
    decisions = [item["decision"] for item in groups]
    if not groups or BLOCKED in decisions or not balanced:
        status, reason = BLOCKED, "INTEGRITY"
    elif ROLLBACK in decisions:
        status, reason = ROLLBACK, "NEGATIVE_LIFT"
    elif not releasable:
        status, reason = OBSERVE, "GATES_PENDING"
    else:
        status, reason = CONTINUE, "POSITIVE_LIFT"
    return {
        "status": status,
        "reason": reason,
        "publishable": publishable,
        "releasable": releasable,
        "version": EXPERIMENT_RULE_VERSION,
    }
