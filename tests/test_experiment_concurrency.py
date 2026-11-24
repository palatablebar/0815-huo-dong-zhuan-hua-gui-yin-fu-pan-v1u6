from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from app.business import DomainIssue
from app.experiment.service import execute
from conftest import experiment_csv


def row(record, group, arm, kind="conversion", day=1, value=100, source=None):
    return [record, group, arm, kind, day, value, source or f"src-{record}", "校核"]


def sample():
    return experiment_csv(
        [row("t1", "G1", "treatment", value=1000, source="s1"),
         row("c1", "G1", "control", value=800, source="s2")]
    )


def test_parallel_rerun_keeps_single_decision(experiment_store):
    data = sample()
    start = Barrier(4)

    def load():
        start.wait(3)
        return execute(experiment_store, data, as_of=40)

    with ThreadPoolExecutor(max_workers=4) as threads:
        results = list(threads.map(lambda _: load(), range(4)))
    assert all(result == results[0] for result in results)
    assert len(experiment_store.list()) == 1
    assert len(experiment_store.history(results[0]["id"])) == 1


def test_parallel_recompute_serialises_revisions(experiment_store):
    base = sample()
    run = execute(experiment_store, base, as_of=40)
    refund_a = base.rstrip(b"\n") + "\nr1,G1,treatment,refund,20,10,s1,退款\n".encode()
    refund_b = base.rstrip(b"\n") + "\nr1,G1,treatment,refund,20,20,s1,退款\n".encode()
    start = Barrier(2)

    def bump(data):
        start.wait(3)
        try:
            return execute(experiment_store, data, batch=run["id"], as_of=40)["revision"]
        except DomainIssue as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as threads:
        results = list(threads.map(bump, [refund_a, refund_b]))
    # 并发重算要么各自串行落成新版本，要么在内容已一致时复用现有版本；
    # 两种情况都不得丢失已落库的判定。
    assert all(isinstance(value, int) for value in results), results
    versions = experiment_store.history(run["id"])
    assert 2 <= len(versions) <= 3
    assert versions[0]["revision"] == 0
    assert experiment_store.load(run["id"])["report"]["groups"][0]["arms"]["treatment"][
        "refund_cents"
    ] in (10, 20)
