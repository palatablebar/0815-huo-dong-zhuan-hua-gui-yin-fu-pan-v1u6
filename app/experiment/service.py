"""实验报告编排：登记、晚到重算、原子回滚切换。

关键约束：
- 同一「报告批次」（相同输入指纹 + 规则版本）重跑命中已有批次，不新增判定。
- 源数据更新或退款晚到时只重算受影响的活动组，其余组沿用上一版判定。
- 回滚/切换为单事务原子操作：失败时旧版判定与全部证据原样保留。
"""

from datetime import datetime, timezone
from hashlib import sha256

from app.business import DomainIssue
from app.config import EXPERIMENT_RULE_VERSION
from app.experiment.pipeline import report as build_report


def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def fingerprint(data):
    return sha256(data).hexdigest()


def batch_id(digest, rule_version=EXPERIMENT_RULE_VERSION):
    return sha256(f"{rule_version}:{digest}".encode()).hexdigest()


def execute(store, data, batch=None, affected=None, as_of=None):
    """登记一份实验报告。

    - 不传 `batch` 时按输入指纹建立/命中报告批次。
    - 传入 `batch` 表示这是同一报告批次的源数据更新：只重算受影响的活动组，
      其余组沿用上一版判定。`affected` 显式指定组；缺省时比较内容自动定位。
    - 同一报告批次沿用首版报告截止日，避免补录旧数据时把成熟度时钟整体后移。
    - 无任何变化时不新增判定版本。
    """
    digest = fingerprint(data)
    identifier = batch or batch_id(digest)

    for attempt in range(5):
        try:
            existing = store.load(identifier)
        except DomainIssue as error:
            if error.code != "RUN_NOT_FOUND":
                raise
            existing = None

        if existing is None:
            report = dict(build_report(data, as_of=as_of))
            report["manifest"] = dict(
                sha256=digest,
                version=EXPERIMENT_RULE_VERSION,
                created=now(),
                bytes=len(data),
                batch_id=identifier,
            )
            return store.register(
                identifier, digest, EXPERIMENT_RULE_VERSION, report,
                report["manifest"]["created"],
            )

        if batch is not None and as_of is None:
            as_of = existing["report"]["as_of_day"]
        fresh = build_report(data, as_of=as_of)
        changed = _changed_groups(existing["report"], fresh, affected)
        if not changed:
            return existing

        merged = _merge(existing["report"], fresh, changed)
        merged["manifest"] = dict(
            existing["report"]["manifest"],
            sha256=digest,
            bytes=len(data),
            updated=now(),
            recomputed=changed,
        )
        try:
            return store.append(identifier, merged, now(), existing["revision"])
        except DomainIssue as error:
            if error.code != "STALE_REVIEW" or attempt == 4:
                raise
    raise DomainIssue("STALE_REVIEW")


def _projection(group):
    """比较两组是否等价的稳定投影（忽略展示字段）。"""
    return {
        "source_fingerprint": group.get("source_fingerprint"),
        "maturity": group["maturity"]["mature"],
        "control": group["control"]["matched"],
        "integrity_ok": group["integrity"]["ok"],
        "issues": group["integrity"]["issues"],
        "decision": group["decision"],
        "reason": group["reason"],
        "lift": group["measure"]["lift_cents"],
        "net": [
            group["arms"]["treatment"]["net_cents"],
            group["arms"]["control"]["net_cents"],
        ],
    }


def _changed_groups(previous, fresh, affected):
    """找出内容或判定发生变化的组。

    显式 `affected` 只是提示重算范围，仍会并入自动检测到的变化组，
    避免因报告截止日推进而漏掉成熟度翻转等隐性变化。
    """
    previous_map = {g["group"]: g for g in previous["groups"]}
    current_map = {g["group"]: g for g in fresh["groups"]}
    if affected is not None:
        unknown = set(affected) - current_map.keys()
        if unknown:
            raise DomainIssue("UNKNOWN_GROUP")
    detected = {
        group for group in previous_map.keys() | current_map.keys()
        if previous_map.get(group) is None
        or current_map.get(group) is None
        or _projection(previous_map[group]) != _projection(current_map[group])
    }
    if affected is not None:
        detected |= set(affected)
    return sorted(detected)


def _merge(previous, fresh, changed):
    """只替换受影响组，其余组沿用上一版对象；新增组按新数据计算。"""
    from app.experiment.pipeline import summarize

    chosen = set(changed)
    kept = [g for g in previous["groups"] if g["group"] not in chosen]
    updated = [g for g in fresh["groups"] if g["group"] in chosen]
    groups = sorted(kept + updated, key=lambda item: item["group"])
    summary = summarize(
        fresh["intake"], groups, fresh["as_of_day"], fresh["as_of_source"]
    )
    summary["balance"]["recalculated"] = sorted(chosen)
    summary["decision"]["recalculated"] = sorted(chosen)
    return summary


def publish(store, identifier, note):
    """签发实验放量判定单：整批必须完整可发布（无隔离、无重叠、行数守恒）。"""
    current = store.load(identifier)
    report = current["report"]
    if not report["balance"]["publishable"]:
        raise DomainIssue("UNRESOLVED_ISSUES")
    if not isinstance(note, str) or not (3 <= len(note.strip()) <= 200):
        raise DomainIssue("REVIEW_FIELDS")
    return store.publish(identifier, now(), note.strip())


def rollback(store, identifier):
    """原子回滚：整批切回上一版生效判定。失败时旧版与证据保持原样。"""
    current = store.load(identifier)
    history = store.history(identifier)
    earlier = [
        item["revision"] for item in history if item["revision"] < current["revision"]
    ]
    if not earlier:
        raise DomainIssue("NO_PRIOR_DECISION")
    return store.switch(identifier, max(earlier), now(), "rollback")
