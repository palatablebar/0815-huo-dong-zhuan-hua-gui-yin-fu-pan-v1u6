import pytest

from app.business import DomainIssue
from app.experiment.evidence import artifact as evidence
from app.experiment.service import execute, publish, rollback
from conftest import experiment_csv

CONV = "conversion"
REFUND = "refund"


def row(record, group, arm, kind=CONV, day=1, value=100, source=None, note="校核"):
    return [record, group, arm, kind, day, value, source or f"src-{record}", note]


def matured(records):
    """补齐成已成熟的同周期两臂小组，方便复用。"""
    return experiment_csv(records)


def wait_window(day=1):
    return dict(as_of=day + 30)


def test_rerun_same_batch_does_not_add_decision(experiment_store):
    data = experiment_csv(
        [row("t1", "G1", "treatment", value=1000),
         row("c1", "G1", "control", value=800)]
    )
    first = execute(experiment_store, data, **wait_window())
    second = execute(experiment_store, data, **wait_window())
    assert first == second
    assert len(experiment_store.history(first["id"])) == 1
    assert len(experiment_store.list()) == 1


def test_new_source_material_starts_new_batch(experiment_store):
    a = experiment_csv(
        [row("t1", "G1", "treatment", value=1000),
         row("c1", "G1", "control", value=800)]
    )
    b = a + experiment_csv([row("t2", "G2", "treatment", value=200)]).split(b"\n", 1)[1]
    one = execute(experiment_store, a, **wait_window())
    two = execute(experiment_store, b, **wait_window())
    assert one["id"] != two["id"]
    assert len(experiment_store.list()) == 2


def test_late_refund_recomputes_only_affected_group(experiment_store):
    base = experiment_csv(
        [row("t1", "G1", "treatment", value=1000, source="s1"),
         row("c1", "G1", "control", value=800, source="s2"),
         row("t2", "G2", "treatment", value=900, source="s3"),
         row("c2", "G2", "control", value=700, source="s4")]
    )
    first = execute(experiment_store, base, **wait_window())
    refund = base.rstrip(b"\n") + "\nr1,G1,treatment,refund,20,100,s1,晚到退款\n".encode()
    second = execute(experiment_store, refund, batch=first["id"], **wait_window())

    assert second["revision"] == 1
    assert second["report"]["manifest"]["recomputed"] == ["G1"]
    assert second["report"]["balance"]["recalculated"] == ["G1"]
    before = next(g for g in first["report"]["groups"] if g["group"] == "G2")
    after = next(g for g in second["report"]["groups"] if g["group"] == "G2")
    assert before == after  # 未受影响组沿用旧版对象
    g1 = next(g for g in second["report"]["groups"] if g["group"] == "G1")
    assert g1["arms"]["treatment"]["net_cents"] == 900


def test_recompute_is_idempotent(experiment_store):
    base = experiment_csv(
        [row("t1", "G1", "treatment", value=1000, source="s1"),
         row("c1", "G1", "control", value=800, source="s2")]
    )
    first = execute(experiment_store, base, **wait_window())
    refund = base.rstrip(b"\n") + "\nr1,G1,treatment,refund,20,100,s1,晚到退款\n".encode()
    execute(experiment_store, refund, batch=first["id"], **wait_window())
    again = execute(experiment_store, refund, batch=first["id"], **wait_window())
    assert again["revision"] == 1
    assert len(experiment_store.history(first["id"])) == 2


def test_update_freezes_report_date(experiment_store):
    base = experiment_csv(
        [row("t1", "G1", "treatment", day=1, value=1000, source="s1"),
         row("c1", "G1", "control", day=1, value=800, source="s2")]
    )
    first = execute(experiment_store, base)
    assert first["report"]["as_of_day"] == 1
    # 補录更晚日期的新数据，但截止日应沿用首版，避免成熟度时钟被整体后移
    grown = base + experiment_csv(
        [row("t2", "G1", "treatment", day=40, value=100, source="s3")]
    ).split(b"\n", 1)[1]
    second = execute(experiment_store, grown, batch=first["id"])
    assert second["report"]["as_of_day"] == 1


def test_old_decision_evidence_is_retained(experiment_store):
    base = experiment_csv(
        [row("t1", "G1", "treatment", value=1000, source="s1"),
         row("c1", "G1", "control", value=800, source="s2")]
    )
    first = execute(experiment_store, base, **wait_window())
    refund = base.rstrip(b"\n") + "\nr1,G1,treatment,refund,20,100,s1,晚到退款\n".encode()
    second = execute(experiment_store, refund, batch=first["id"], **wait_window())

    history = experiment_store.history(first["id"])
    assert [item["revision"] for item in history] == [0, 1]
    old = experiment_store.load_revision(first["id"], 0)
    assert old["report"] == first["report"]
    packet = __import__("json").loads(
        evidence(second, history, experiment_store.events(first["id"]))
    )
    assert [v["revision"] for v in packet["versions"]] == [0, 1]
    assert packet["versions"][0]["report"]["groups"][0]["arms"]["treatment"]["net_cents"] == 1000


def test_publish_records_final_state(experiment_store):
    data = experiment_csv(
        [row("t1", "G1", "treatment", value=1000),
         row("c1", "G1", "control", value=800)]
    )
    run = execute(experiment_store, data, **wait_window())
    done = publish(experiment_store, run["id"], "同周期对照完整")
    assert done["published"] is True and done["published_at"]
    with pytest.raises(DomainIssue, match="RUN_FINALIZED"):
        publish(experiment_store, run["id"], "再次签发")


def test_rollback_switches_atomically(experiment_store):
    base = experiment_csv(
        [row("t1", "G1", "treatment", value=1000, source="s1"),
         row("c1", "G1", "control", value=800, source="s2")]
    )
    first = execute(experiment_store, base, **wait_window())
    refund = base.rstrip(b"\n") + "\nr1,G1,treatment,refund,20,2000,s1,退款超毛额\n".encode()
    second = execute(experiment_store, refund, batch=first["id"], **wait_window())
    assert second["status"] == "BLOCKED"

    restored = rollback(experiment_store, first["id"])
    assert restored["revision"] == 0
    assert restored["report"] == first["report"]
    # 证据链仍保留被回滚的版本，不丢记录
    assert [item["revision"] for item in experiment_store.history(first["id"])] == [0, 1]


def test_rollback_without_history_is_rejected(experiment_store):
    data = experiment_csv(
        [row("t1", "G1", "treatment", value=1000),
         row("c1", "G1", "control", value=800)]
    )
    run = execute(experiment_store, data, **wait_window())
    with pytest.raises(DomainIssue, match="NO_PRIOR_DECISION"):
        rollback(experiment_store, run["id"])


def test_rollback_failure_keeps_old_version(experiment_store):
    base = experiment_csv(
        [row("t1", "G1", "treatment", value=1000, source="s1"),
         row("c1", "G1", "control", value=800, source="s2")]
    )
    first = execute(experiment_store, base, **wait_window())
    refund = base.rstrip(b"\n") + "\nr1,G1,treatment,refund,20,100,s1,退款\n".encode()
    second = execute(experiment_store, refund, batch=first["id"], **wait_window())

    # 指向不存在的版本时切换必须失败，且当前版本不被改动
    with pytest.raises(DomainIssue, match="REVISION_NOT_FOUND"):
        experiment_store.switch(first["id"], 999, "now")
    current = experiment_store.load(first["id"])
    assert current["revision"] == second["revision"] == 1
    assert current["report"] == second["report"]


def test_new_group_is_computed_in_shared_batch(experiment_store):
    base = experiment_csv(
        [row("t1", "G1", "treatment", value=1000, source="s1"),
         row("c1", "G1", "control", value=800, source="s2")]
    )
    first = execute(experiment_store, base, **wait_window())
    grown = base + experiment_csv(
        [row("t2", "G2", "treatment", value=100),
         row("c2", "G2", "control", value=100)]
    ).split(b"\n", 1)[1]
    second = execute(experiment_store, grown, batch=first["id"], **wait_window())
    assert [g["group"] for g in second["report"]["groups"]] == ["G1", "G2"]
    assert second["report"]["manifest"]["recomputed"] == ["G2"]
    untouched = next(g for g in second["report"]["groups"] if g["group"] == "G1")
    original = next(g for g in first["report"]["groups"] if g["group"] == "G1")
    assert untouched == original
