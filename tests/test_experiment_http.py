import io

from conftest import experiment_csv


def row(record, group, arm, kind="conversion", day=1, value=100, source=None):
    return [record, group, arm, kind, day, value, source or f"src-{record}", "校核"]


def upload(client, data, **form):
    payload = {"file": (io.BytesIO(data), "input.csv"), **form}
    return client.post("/api/experiments", data=payload)


def test_ready_sample_is_releasable(experiment_client):
    result = experiment_client.post("/api/experiments", data={"sample": "ready"})
    assert result.status_code == 200
    assert result.json["status"] == "CONTINUE"
    assert result.json["report"]["balance"]["releasable"] is True


def test_risk_sample_is_blocked(experiment_client):
    result = experiment_client.post("/api/experiments", data={"sample": "risk"})
    assert result.status_code == 200
    assert result.json["status"] == "BLOCKED"
    assert result.json["report"]["balance"]["releasable"] is False


def test_rerun_is_idempotent_over_http(experiment_client):
    first = experiment_client.post("/api/experiments", data={"sample": "ready"})
    second = experiment_client.post("/api/experiments", data={"sample": "ready"})
    assert first.json["id"] == second.json["id"]
    assert len(experiment_client.get("/api/experiments").json["items"]) == 1


def test_detail_exposes_version_chain(experiment_client):
    run = experiment_client.post("/api/experiments", data={"sample": "ready"}).json
    detail = experiment_client.get(f"/api/experiments/{run['id']}")
    assert detail.status_code == 200
    assert detail.json["versions"][0]["revision"] == 0
    assert detail.json["events"][0]["kind"] == "created"


def test_publish_then_rollback_over_http(experiment_client):
    run = experiment_client.post("/api/experiments", data={"sample": "ready"}).json
    late = experiment_csv(
        [row("t1", "G1", "treatment", value=1000, source="s1"),
         row("c1", "G1", "control", value=800, source="s2"),
         row("r1", "G1", "treatment", "refund", 9, 50, "s1")]
    )
    update = upload(experiment_client, late, batch=run["id"])
    assert update.json["revision"] == 1

    published = experiment_client.post(
        f"/api/experiments/{run['id']}/publish", json={"note": "财务已核对净额"}
    )
    assert published.status_code == 200 and published.json["published"] is True

    rolled = experiment_client.post(f"/api/experiments/{run['id']}/rollback")
    assert rolled.status_code == 200 and rolled.json["revision"] == 0


def test_publish_rejects_short_note(experiment_client):
    run = experiment_client.post("/api/experiments", data={"sample": "ready"}).json
    result = experiment_client.post(
        f"/api/experiments/{run['id']}/publish", json={"note": "x"}
    )
    assert result.status_code == 422 and result.json["code"] == "REVIEW_FIELDS"


def test_publish_rejects_unpublishable(experiment_client):
    run = experiment_client.post("/api/experiments", data={"sample": "risk"}).json
    result = experiment_client.post(
        f"/api/experiments/{run['id']}/publish", json={"note": "强行放量"}
    )
    assert result.status_code == 409 and result.json["code"] == "UNRESOLVED_ISSUES"


def test_evidence_download_has_all_versions(experiment_client):
    run = experiment_client.post("/api/experiments", data={"sample": "ready"}).json
    late = experiment_csv(
        [row("t1", "G1", "treatment", value=1000, source="s1"),
         row("c1", "G1", "control", value=800, source="s2"),
         row("r1", "G1", "treatment", "refund", 9, 50, "s1")]
    )
    upload(experiment_client, late, batch=run["id"])
    result = experiment_client.get(f"/api/experiments/{run['id']}/evidence")
    assert result.status_code == 200
    assert result.headers["Content-Disposition"].startswith("attachment")
    assert [v["revision"] for v in result.json["versions"]] == [0, 1]


def test_unknown_batch_is_404(experiment_client):
    assert experiment_client.get("/api/experiments/unknown").status_code == 404
    assert (
        experiment_client.post("/api/experiments/unknown/rollback").status_code == 404
    )


def test_experiment_and_attribution_stores_are_separate(experiment_client):
    experiment_client.post("/api/experiments", data={"sample": "ready"})
    assert experiment_client.get("/api/runs").json == {"items": []}
