"""实验批次采信：记录键去重、来源唯一性与跨组重叠检查。

每笔转化以 `source` 作为业务来源键。一个来源键只能出现在一个活动组中，
且同一组内只能出现一次；任何重复来源或跨组重叠都会列出原始记录键，
并把相关活动组整组标记为不可发布。
"""

from collections import Counter, defaultdict

from app.business import DomainIssue
from app.experiment.schema import HEADER, parse_row
from app.intake.reader import records


def _reject(line, values, reason):
    record = values[0][:36] if values else ""
    group = values[1][:36].strip() if len(values) > 1 else ""
    return dict(line=line, record=record, group=group, reason=reason)


def _partition(candidates):
    """按记录键去重：冲突副本全部隔离，完全一致的重放只保留首条。"""
    by_key = defaultdict(list)
    for line, row in candidates:
        by_key[row["record"]].append((line, row))
    accepted, rejected = [], []
    for key, copies in by_key.items():
        first = copies[0][1]
        if any(row != first for _, row in copies):
            rejected.extend(
                dict(line=line, record=key, group=row["group"],
                     reason="DUPLICATE_CONFLICT")
                for line, row in copies
            )
            continue
        accepted.append(first)
        rejected.extend(
            dict(line=line, record=key, group=row["group"],
                 reason="DUPLICATE_REPLAY")
            for line, row in copies[1:]
        )
    return accepted, rejected


def _issue(issues, group, code, keys, **extra):
    entry = dict(code=code, record_keys=sorted(set(keys)))
    entry.update(extra)
    if entry not in issues[group]:
        issues[group].append(entry)


def _source_checks(rows, issues):
    conversions = [r for r in rows if r["kind"] == "conversion"]
    refunds = [r for r in rows if r["kind"] == "refund"]

    by_source = defaultdict(list)
    for row in conversions:
        by_source[row["source"]].append(row)

    # 一个来源键只能属于一个活动组，且组内只能有一笔转化。
    for source, copies in sorted(by_source.items()):
        groups = sorted({row["group"] for row in copies})
        keys = [row["record"] for row in copies]
        if len(groups) > 1:
            for group in groups:
                _issue(issues, group, "CROSS_GROUP_OVERLAP", keys,
                       source=source, groups=groups)
        elif len(copies) > 1:
            _issue(issues, groups[0], "DUPLICATE_SOURCE", keys, source=source)

    # 退款必须指向本组已采信的转化，金额不得超过毛额，臂必须一致。
    paid = defaultdict(int)
    for refund in refunds:
        matches = by_source.get(refund["source"], [])
        if not matches:
            _issue(issues, refund["group"], "UNMATCHED_REFUND",
                   [refund["record"]], source=refund["source"])
            continue
        same_group = [row for row in matches if row["group"] == refund["group"]]
        if not same_group:
            involved = sorted({refund["group"], *[row["group"] for row in matches]})
            _issue(issues, refund["group"], "CROSS_GROUP_OVERLAP",
                   [refund["record"], *[row["record"] for row in matches]],
                   source=refund["source"], groups=involved)
            for group in involved:
                if group != refund["group"]:
                    _issue(issues, group, "CROSS_GROUP_OVERLAP",
                           [refund["record"], *[row["record"] for row in matches]],
                           source=refund["source"], groups=involved)
            continue
        if any(row["arm"] != refund["arm"] for row in same_group):
            _issue(issues, refund["group"], "REFUND_ARM_MISMATCH",
                   [refund["record"], *[row["record"] for row in same_group]],
                   source=refund["source"])
        paid[(refund["group"], refund["source"])] += refund["value_cents"]

    for (group, source), total in sorted(paid.items()):
        gross = sum(row["value_cents"] for row in by_source[source]
                    if row["group"] == group)
        if total > gross:
            _issue(issues, group, "REFUND_EXCEEDS_GROSS",
                   [row["record"] for row in by_source[source]
                    if row["group"] == group]
                   + [r["record"] for r in refunds
                      if r["source"] == source and r["group"] == group],
                   source=source, gross_cents=gross, refund_cents=total)


def inspect(data):
    counted = repeated = blanks = 0
    candidates, rejected = [], []
    for line, values in records(data, HEADER):
        counted += 1
        if not any(v.strip() for v in values):
            blanks += 1
            continue
        if tuple(values) == HEADER:
            repeated += 1
            continue
        try:
            candidates.append((line, parse_row(values)))
        except DomainIssue as error:
            rejected.append(_reject(line, values, error.code))

    accepted, conflicts = _partition(candidates)
    rejects = sorted(rejected + conflicts, key=lambda row: (row["line"], row["record"]))

    accepted_groups = {row["group"] for row in accepted}
    rejected_groups = {row["group"] for row in rejects if row["group"]}
    groups = sorted(accepted_groups | rejected_groups)

    issues = defaultdict(list)
    for reject in rejects:
        if reject["group"]:
            _issue(issues, reject["group"], "ISOLATED_ROW", [reject["record"]])

    _source_checks(accepted, issues)

    return dict(
        input=counted,
        accepted=len(accepted),
        repeated=repeated,
        blank=blanks,
        rejected=len(rejects),
        reasons=dict(sorted(Counter(r["reason"] for r in rejects).items())),
        isolation=rejects,
        rows=accepted,
        groups=groups,
        issues={group: sorted(items, key=lambda item: item["code"])
                for group, items in sorted(issues.items())},
    )
