"""实验放量判定：成熟度、同周期对照与退款净额增量。

判定口径（财务认可增量所需）：
1. 样本成熟：组内每笔转化都经过完整退款观察窗（`MATURITY_DAYS`）后才计入。
2. 对照匹配：同一组必须同时具备 treatment 与 control 两个臂，
   且两臂的转化日集合完全一致（同周期对照完整）。
3. 净额齐备：增量按扣除退款后的净额计算（毛额减退款）。
4. 只有同时满足以上三项，才按净额增量正负给出 CONTINUE / OBSERVE / ROLLBACK。
   未成熟但暂显优势的组一律 OBSERVE，绝不提前放量。
"""

from app.config import MATURITY_DAYS, MIN_PER_ARM
from app.experiment.schema import ARMS

CONTINUE = "CONTINUE"
OBSERVE = "OBSERVE"
ROLLBACK = "ROLLBACK"
BLOCKED = "BLOCKED"

DECISIONS = (CONTINUE, OBSERVE, ROLLBACK, BLOCKED)


def _arm(rows, arm):
    conversions = [r for r in rows if r["arm"] == arm and r["kind"] == "conversion"]
    refunds = [r for r in rows if r["arm"] == arm and r["kind"] == "refund"]
    gross = sum(r["value_cents"] for r in conversions)
    refunded = sum(r["value_cents"] for r in refunds)
    return {
        "conversions": len(conversions),
        "gross_cents": gross,
        "refund_cents": refunded,
        "net_cents": gross - refunded,
        "days": sorted({r["day"] for r in conversions}),
        "conversion_keys": sorted(r["record"] for r in conversions),
        "refund_keys": sorted(r["record"] for r in refunds),
    }


def _maturity(rows, as_of):
    conversions = [r for r in rows if r["kind"] == "conversion"]
    immature = sorted(
        r["record"] for r in conversions if r["day"] + MATURITY_DAYS > as_of
    )
    return {
        "as_of_day": as_of,
        "window_days": MATURITY_DAYS,
        "mature": not immature,
        "immature_keys": immature,
    }


def _control(treatment, control):
    if not treatment["days"] or not control["days"]:
        return {"matched": False, "reason": "ARM_MISSING"}
    if treatment["days"] != control["days"]:
        return {
            "matched": False,
            "reason": "PERIOD_MISMATCH",
            "treatment_days": treatment["days"],
            "control_days": control["days"],
        }
    return {"matched": True, "reason": None, "days": treatment["days"]}


def evaluate(group, rows, issues, as_of):
    treatment = _arm(rows, "treatment")
    control = _arm(rows, "control")
    maturity = _maturity(rows, as_of)
    matched = _control(treatment, control)

    sample_ok = (
        treatment["conversions"] >= MIN_PER_ARM
        and control["conversions"] >= MIN_PER_ARM
    )
    lift = treatment["net_cents"] - control["net_cents"]
    sign = (lift > 0) - (lift < 0)

    gate = []
    if not maturity["mature"]:
        gate.append("NOT_MATURED")
    if not matched["matched"]:
        gate.append(matched["reason"])
    if not sample_ok:
        gate.append("SAMPLE_INSUFFICIENT")

    integrity_ok = not issues
    if not integrity_ok:
        decision, reason = BLOCKED, "INTEGRITY"
    elif gate:
        decision, reason = OBSERVE, gate[0]
    elif sign > 0:
        decision, reason = CONTINUE, "POSITIVE_LIFT"
    elif sign < 0:
        decision, reason = ROLLBACK, "NEGATIVE_LIFT"
    else:
        decision, reason = OBSERVE, "NO_LIFT"

    ramp_allowed = (
        decision == CONTINUE
        and integrity_ok
        and maturity["mature"]
        and matched["matched"]
    )

    return {
        "group": group,
        "records": sorted(r["record"] for r in rows),
        "arms": {arm: (treatment if arm == "treatment" else control) for arm in ARMS},
        "integrity": {
            "ok": integrity_ok,
            "issues": issues,
            "record_keys": sorted(
                {key for issue in issues for key in issue["record_keys"]}
            ),
        },
        "maturity": maturity,
        "control": matched,
        "sample": {"min_per_arm": MIN_PER_ARM, "ok": sample_ok},
        "measure": {
            "treatment_net_cents": treatment["net_cents"],
            "control_net_cents": control["net_cents"],
            "lift_cents": lift,
            "gross_cents": treatment["gross_cents"] + control["gross_cents"],
            "refund_cents": treatment["refund_cents"] + control["refund_cents"],
            "sign": sign,
        },
        "gates": gate,
        "decision": decision,
        "reason": reason,
        "provisional_advantage": bool(sign > 0 and gate),
        "ramp_allowed": ramp_allowed,
        "publishable": integrity_ok,
    }
