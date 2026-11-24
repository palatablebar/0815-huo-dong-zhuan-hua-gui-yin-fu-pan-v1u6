from flask import Blueprint, Response, current_app, jsonify, request

from app.business import DomainIssue
from app.evidence.render import artifact
from app.experiment import service as experiment
from app.experiment.evidence import artifact as experiment_artifact
from app.inputs import EXPERIMENT_SAMPLES, read_input
from app.modules.pipeline import run
from app.review.service import execute, review

api = Blueprint("api", __name__, url_prefix="/api")
STAGES = {"intake": 1, "prepare": 2, "calculate": 3, "policy": 4, "balance": 5}


@api.post("/stages/<stage>")
def preview(stage):
    if stage not in STAGES:
        raise DomainIssue("STAGE_UNKNOWN")
    return jsonify(run(read_input(), STAGES[stage]))


@api.route("/runs", methods=["GET", "POST"])
def runs():
    store = current_app.extensions["runs"]
    if request.method == "GET":
        return jsonify(items=store.list())
    return jsonify(execute(store, read_input()))


@api.route("/runs/<run_id>", methods=["GET", "PATCH"])
def batch(run_id):
    store = current_app.extensions["runs"]
    if request.method == "GET":
        return jsonify(store.load(run_id))
    return jsonify(review(store, run_id, request.get_json(silent=True)))


@api.get("/runs/<run_id>/evidence")
def export(run_id):
    report = current_app.extensions["runs"].load(run_id)
    return Response(
        artifact(report),
        mimetype="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="review-{report["id"][:12]}.json"',
            "Cache-Control": "no-store",
        },
    )


# -- 实验放量判定 -----------------------------------------------------------

def _experiment_store():
    return current_app.extensions["experiments"]


def _expanded(store, batch_id):
    """当前判定 + 完整版本链 + 审计事件，供工作台与证据复用。"""
    return dict(
        store.load(batch_id),
        versions=store.history(batch_id),
        events=store.events(batch_id),
    )


def _json():
    value = request.get_json(silent=True)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise DomainIssue("REVIEW_FIELDS")
    return value


@api.route("/experiments", methods=["GET", "POST"])
def experiments():
    store = _experiment_store()
    if request.method == "GET":
        return jsonify(items=store.list())
    batch = request.form.get("batch") or None
    affected = request.form.getlist("affected") or None
    as_of = request.form.get("as_of")
    result = experiment.execute(
        store,
        read_input(EXPERIMENT_SAMPLES),
        batch=batch,
        affected=affected,
        as_of=int(as_of) if as_of not in (None, "") else None,
    )
    return jsonify(_expanded(store, result["id"]))


@api.get("/experiments/<batch_id>")
def experiment_detail(batch_id):
    return jsonify(_expanded(_experiment_store(), batch_id))


@api.post("/experiments/<batch_id>/publish")
def experiment_publish(batch_id):
    store = _experiment_store()
    values = _json()
    experiment.publish(store, batch_id, values.get("note"))
    return jsonify(_expanded(store, batch_id))


@api.post("/experiments/<batch_id>/rollback")
def experiment_rollback(batch_id):
    store = _experiment_store()
    experiment.rollback(store, batch_id)
    return jsonify(_expanded(store, batch_id))


@api.get("/experiments/<batch_id>/evidence")
def experiment_evidence(batch_id):
    store = _experiment_store()
    batch = store.load(batch_id)
    history = store.history(batch_id)
    events = store.events(batch_id)
    return Response(
        experiment_artifact(batch, history, events),
        mimetype="application/json",
        headers={
            "Content-Disposition":
                f'attachment; filename="experiment-{batch_id[:12]}.json"',
            "Cache-Control": "no-store",
        },
    )
