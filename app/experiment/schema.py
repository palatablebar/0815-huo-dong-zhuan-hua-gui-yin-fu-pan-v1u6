"""实验判定单的输入字段与行级校验。

与归因复盘不同，实验行以活动组（group）和实验臂（arm）组织：
`conversion` 记录一笔转化及其毛额，`refund` 记录一笔退款。
记录键、活动组和来源键都保留原始字符串（含前导零）。
"""

import re

from app.business import DomainIssue
from app.intake.numeric import quantity

HEADER = ("record", "group", "arm", "kind", "day", "value_cents", "source", "note")

ARMS = ("treatment", "control")
KINDS = ("conversion", "refund")

IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,35}")
SOURCE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}")


def parse_row(values):
    if len(values) != len(HEADER):
        raise DomainIssue("COLUMN_COUNT")
    row = dict(zip(HEADER, values))
    for key in ("record", "group", "arm", "kind"):
        row[key] = row[key].strip()
    if not IDENTIFIER.fullmatch(row["record"]):
        raise DomainIssue("BAD_IDENTIFIER")
    if not IDENTIFIER.fullmatch(row["group"]):
        raise DomainIssue("BAD_IDENTIFIER")
    if row["arm"] not in ARMS:
        raise DomainIssue("UNKNOWN_ARM")
    if row["kind"] not in KINDS:
        raise DomainIssue("UNKNOWN_KIND")
    row["day"] = quantity(row["day"])
    row["value_cents"] = quantity(row["value_cents"])
    row["source"] = row["source"].strip()
    if row["kind"] == "conversion":
        if not row["source"]:
            raise DomainIssue("SOURCE_REQUIRED")
        if not SOURCE.fullmatch(row["source"]):
            raise DomainIssue("BAD_SOURCE")
    elif row["source"] and not SOURCE.fullmatch(row["source"]):
        raise DomainIssue("BAD_SOURCE")
    if len(row["note"]) > 200:
        raise DomainIssue("NOTE_TOO_LONG")
    return row
