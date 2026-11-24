import pytest

from app.business import DomainIssue
from app.experiment.intake import inspect
from app.experiment.pipeline import report
from conftest import experiment_csv

CONV = "conversion"
REFUND = "refund"
_MISSING = object()


def row(record, group, arm, kind=CONV, day=1, value=100, source=_MISSING, note="校核"):
    key = f"src-{record}" if source is _MISSING else source
    return [record, group, arm, kind, day, value, key, note]


def group_of(data, code, as_of=None):
    return next(g for g in report(data, as_of=as_of)["groups"] if g["group"] == code)


def test_bom_and_leading_zero_identifier():
    data = b"\xef\xbb\xbf" + experiment_csv([row("0007", "G1", "treatment")])
    assert inspect(data)["rows"][0]["record"] == "0007"


def test_repeated_header_counted_and_blank_skipped():
    data = experiment_csv([row("r1", "G1", "treatment")])
    data += b"record,group,arm,kind,day,value_cents,source,note\n\n"
    result = inspect(data)
    assert result["repeated"] == 1 and result["blank"] == 1


def test_record_conflict_isolates_both_copies():
    data = experiment_csv(
        [row("r1", "G1", "treatment", value=100), row("r1", "G1", "treatment", value=200)]
    )
    result = inspect(data)
    assert not result["rows"]
    assert result["reasons"] == {"DUPLICATE_CONFLICT": 2}


def test_confident_duplicate_replay_keeps_first():
    data = experiment_csv([row("r1", "G1", "treatment"), row("r1", "G1", "treatment")])
    result = inspect(data)
    assert result["accepted"] == 1 and result["reasons"] == {"DUPLICATE_REPLAY": 1}


def test_conversion_requires_source():
    data = experiment_csv([row("r1", "G1", "treatment", source="")])
    assert inspect(data)["reasons"] == {"SOURCE_REQUIRED": 1}


def test_unknown_arm_rejected():
    data = experiment_csv([row("r1", "G1", "holdout")])
    assert inspect(data)["reasons"] == {"UNKNOWN_ARM": 1}


def test_duplicate_source_within_group_lists_keys_and_blocks():
    data = experiment_csv(
        [row("a1", "G1", "treatment", source="shared"),
         row("a2", "G1", "treatment", source="shared"),
         row("c1", "G1", "control")]
    )
    group = group_of(data, "G1")
    assert group["decision"] == "BLOCKED"
    assert group["integrity"]["record_keys"] == ["a1", "a2"]
    assert [i["code"] for i in group["integrity"]["issues"]] == ["DUPLICATE_SOURCE"]


def test_cross_group_overlap_blocks_every_involved_group():
    data = experiment_csv(
        [row("t1", "G1", "treatment", source="shared"),
         row("c1", "G1", "control"),
         row("t2", "G2", "treatment", source="shared"),
         row("c2", "G2", "control")]
    )
    one, two = group_of(data, "G1"), group_of(data, "G2")
    assert one["decision"] == two["decision"] == "BLOCKED"
    assert one["integrity"]["record_keys"] == ["t1", "t2"]
    assert "CROSS_GROUP_OVERLAP" in {i["code"] for i in one["integrity"]["issues"]}


def test_unmatched_refund_blocks_group():
    data = experiment_csv(
        [row("t1", "G1", "treatment"), row("c1", "G1", "control"),
         row("r1", "G1", "treatment", kind=REFUND, source="ghost")]
    )
    group = group_of(data, "G1")
    assert group["integrity"]["ok"] is False
    assert "UNMATCHED_REFUND" in {i["code"] for i in group["integrity"]["issues"]}


def test_refund_exceeding_gross_blocks():
    data = experiment_csv(
        [row("t1", "G1", "treatment", value=100), row("c1", "G1", "control"),
         row("r1", "G1", "treatment", kind=REFUND, value=150, source="src-t1")]
    )
    codes = {i["code"] for i in group_of(data, "G1")["integrity"]["issues"]}
    assert "REFUND_EXCEEDS_GROSS" in codes


def test_refund_arm_mismatch_blocks():
    data = experiment_csv(
        [row("t1", "G1", "treatment"), row("c1", "G1", "control"),
         row("r1", "G1", "control", kind=REFUND, value=10, source="src-t1")]
    )
    codes = {i["code"] for i in group_of(data, "G1")["integrity"]["issues"]}
    assert "REFUND_ARM_MISMATCH" in codes


def test_net_lift_includes_late_refund():
    data = experiment_csv(
        [row("t1", "G1", "treatment", day=1, value=1000, source="s1"),
         row("c1", "G1", "control", day=1, value=800, source="s2"),
         row("r1", "G1", "treatment", kind=REFUND, day=9, value=200, source="s1")]
    )
    group = group_of(data, "G1")
    assert group["arms"]["treatment"]["net_cents"] == 800
    assert group["measure"]["lift_cents"] == 0
    assert group["decision"] == "OBSERVE"


def test_mature_positive_continues():
    data = experiment_csv(
        [row("t1", "G1", "treatment", day=1, value=1000),
         row("c1", "G1", "control", day=1, value=800)]
    )
    group = group_of(data, "G1", as_of=8)
    assert group["maturity"]["mature"] is True
    assert group["decision"] == "CONTINUE" and group["ramp_allowed"] is True


def test_mature_negative_rolls_back():
    data = experiment_csv(
        [row("t1", "G1", "treatment", day=1, value=500),
         row("c1", "G1", "control", day=1, value=900)]
    )
    assert group_of(data, "G1", as_of=8)["decision"] == "ROLLBACK"


def test_immature_advantage_does_not_ramp():
    data = experiment_csv(
        [row("t1", "G1", "treatment", day=15, value=1000),
         row("c1", "G1", "control", day=15, value=700)]
    )
    group = group_of(data, "G1")
    assert group["decision"] == "OBSERVE"
    assert group["provisional_advantage"] is True
    assert group["ramp_allowed"] is False


def test_period_mismatch_is_not_controlled():
    data = experiment_csv(
        [row("t1", "G1", "treatment", day=1), row("c1", "G1", "control", day=2),
         row("x1", "G1", "control", day=1)]
    )
    group = group_of(data, "G1")
    assert group["control"]["matched"] is False
    assert group["decision"] == "OBSERVE"


def test_missing_arm_is_observed_not_ramped():
    data = experiment_csv([row("t1", "G1", "treatment", value=900)])
    group = group_of(data, "G1")
    assert group["control"]["reason"] == "ARM_MISSING"
    assert group["decision"] == "OBSERVE"


def test_isolated_row_blocks_group_and_batch():
    data = experiment_csv(
        [row("t1", "G1", "treatment"), row("c1", "G1", "control"),
         ["bad id!", "G1", "treatment", CONV, 1, 10, "s", "x"]]
    )
    result = report(data)
    assert group_of(data, "G1")["decision"] == "BLOCKED"
    assert result["balance"]["releasable"] is False


def test_ready_sample_releases():
    from pathlib import Path

    data = Path(__file__).resolve().parents[1].joinpath(
        "sample_data", "experiment_ready.csv"
    ).read_bytes()
    result = report(data)
    assert [g["decision"] for g in result["groups"]] == ["CONTINUE", "CONTINUE"]
    assert result["balance"]["releasable"] is True


def test_empty_group_set_is_blocked():
    from app.experiment.pipeline import summarize

    intake = dict(input=0, accepted=0, rejected=0, blank=0, repeated=0, issues={})
    result = summarize(intake, [], 0)
    assert result["decision"]["status"] == "BLOCKED"
    assert result["balance"]["releasable"] is False


def test_risk_sample_blocks_every_unsafe_group():
    from pathlib import Path

    data = Path(__file__).resolve().parents[1].joinpath(
        "sample_data", "experiment_risk.csv"
    ).read_bytes()
    result = report(data)
    decisions = {g["group"]: g["decision"] for g in result["groups"]}
    assert decisions == {
        "R1": "OBSERVE",
        "R2": "ROLLBACK",
        "R3": "BLOCKED",
        "R4": "BLOCKED",
        "R5": "BLOCKED",
    }
    assert result["balance"]["releasable"] is False


def test_row_conservation(experiment_ready):
    result = report(experiment_ready)
    checks = result["balance"]
    assert checks["input"] == checks["accounted"] == checks["observed"]


def test_publish_requires_publishable(experiment_store):
    from app.experiment.service import execute, publish

    data = experiment_csv(
        [row("t1", "G1", "treatment", value=1000),
         row("c1", "G1", "control", value=800),
         ["bad id!", "G1", "treatment", CONV, 1, 10, "s", "x"]]
    )
    run = execute(experiment_store, data)
    with pytest.raises(DomainIssue, match="UNRESOLVED_ISSUES"):
        publish(experiment_store, run["id"], "试图放量")
