"""实验判定单持久化。

结构分离「不可变证据链」「当前生效指针」与「审计事件」：

- `experiment_batches`：报告批次元数据与当前生效版本指针。
- `experiment_decisions`：每个修订版本的完整报告与判定，只追加不覆盖。
- `experiment_events`：发布、回滚、重算等审计事件。

切换生效版本（发布/回滚）在单个 `BEGIN IMMEDIATE` 事务里完成，任何一步失败
整体回滚，旧版判定与全部历史证据保持不变，不会丢记录。
"""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from app.business import DomainIssue

SCHEMA = """
CREATE TABLE IF NOT EXISTS experiment_batches (
    id TEXT PRIMARY KEY,
    fingerprint TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    created TEXT NOT NULL,
    updated TEXT NOT NULL,
    revision INTEGER NOT NULL,
    published INTEGER NOT NULL DEFAULT 0,
    published_at TEXT,
    UNIQUE(fingerprint, rule_version)
);
CREATE TABLE IF NOT EXISTS experiment_decisions (
    batch_id TEXT NOT NULL REFERENCES experiment_batches(id),
    revision INTEGER NOT NULL,
    decision TEXT NOT NULL,
    reason TEXT NOT NULL,
    report TEXT NOT NULL,
    created TEXT NOT NULL,
    PRIMARY KEY (batch_id, revision)
);
CREATE TABLE IF NOT EXISTS experiment_events (
    batch_id TEXT NOT NULL REFERENCES experiment_batches(id),
    ordinal INTEGER NOT NULL,
    kind TEXT NOT NULL,
    detail TEXT NOT NULL,
    created TEXT NOT NULL,
    PRIMARY KEY (batch_id, ordinal)
);
"""


class ExperimentStore:
    def __init__(self, path):
        self.path = Path(path)
        self.shared = str(path) == ":memory:"
        self._keep = None

    @contextmanager
    def connect(self, write=False):
        if self.shared:
            db = self._connection()
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            db = sqlite3.connect(self.path, timeout=15, isolation_level=None)
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys = ON")
            db.executescript(SCHEMA)
        try:
            if write:
                db.execute("BEGIN IMMEDIATE")
                try:
                    yield db
                except BaseException:
                    db.execute("ROLLBACK")
                    raise
                else:
                    db.execute("COMMIT")
            else:
                yield db
        finally:
            if not self.shared:
                db.close()

    def _connection(self):
        if self._keep is None:
            self._keep = sqlite3.connect(":memory:", isolation_level=None)
            self._keep.row_factory = sqlite3.Row
            self._keep.execute("PRAGMA foreign_keys = ON")
            self._keep.executescript(SCHEMA)
        return self._keep

    # -- 写入 --------------------------------------------------------------
    def register(self, identifier, digest, rule_version, report, created):
        """幂等登记：相同批次重跑不新增判定版本。"""
        payload = _dump(report)
        status, reason = report["decision"]["status"], report["decision"]["reason"]
        with self.connect(write=True) as db:
            cursor = db.execute(
                "INSERT INTO experiment_batches"
                "(id,fingerprint,rule_version,created,updated,revision,published)"
                " VALUES (?,?,?,?,?,0,0) ON CONFLICT(id) DO NOTHING",
                (identifier, digest, rule_version, created, created),
            )
            if cursor.rowcount == 1:
                db.execute(
                    "INSERT INTO experiment_decisions"
                    "(batch_id,revision,decision,reason,report,created)"
                    " VALUES (?,0,?,?,?,?)",
                    (identifier, status, reason, payload, created),
                )
                self._event(db, identifier, "created", {"revision": 0}, created)
        return self.load(identifier)

    def append(self, identifier, report, created, expected_revision):
        """追加新版本并前移指针。修订号取历史最大值加一，避免回滚后冲突。"""
        with self.connect(write=True) as db:
            state = self._state(db, identifier)
            if state["revision"] != expected_revision:
                raise DomainIssue("STALE_REVIEW")
            revision = state["max_revision"] + 1
            self._append(db, identifier, revision, report, created)
        return self.load(identifier)

    def publish(self, identifier, created, note):
        with self.connect(write=True) as db:
            state = self._state(db, identifier)
            if state["published"]:
                raise DomainIssue("RUN_FINALIZED")
            db.execute(
                "UPDATE experiment_batches SET published=1,published_at=?,updated=?"
                " WHERE id=?",
                (created, created, identifier),
            )
            self._event(
                db, identifier, "published",
                {"revision": state["revision"], "note": note}, created,
            )
        return self.load(identifier)

    def switch(self, identifier, target_revision, created, kind="rollback", note=""):
        """原子切换生效版本到历史中的某一版，不新增、不删除证据。"""
        with self.connect(write=True) as db:
            state = self._state(db, identifier)
            exists = db.execute(
                "SELECT 1 FROM experiment_decisions WHERE batch_id=? AND revision=?",
                (identifier, target_revision),
            ).fetchone()
            if exists is None:
                raise DomainIssue("REVISION_NOT_FOUND")
            db.execute(
                "UPDATE experiment_batches SET revision=?,updated=?,published=0"
                " WHERE id=?",
                (target_revision, created, identifier),
            )
            self._event(
                db, identifier, kind,
                {"from": state["revision"], "to": target_revision, "note": note},
                created,
            )
        return self.load(identifier)

    @staticmethod
    def _append(db, identifier, revision, report, created):
        db.execute(
            "INSERT INTO experiment_decisions"
            "(batch_id,revision,decision,reason,report,created)"
            " VALUES (?,?,?,?,?,?)",
            (
                identifier,
                revision,
                report["decision"]["status"],
                report["decision"]["reason"],
                _dump(report),
                created,
            ),
        )
        db.execute(
            "UPDATE experiment_batches SET revision=?,updated=?,published=0"
            " WHERE id=?",
            (revision, created, identifier),
        )
        db.execute(
            "INSERT INTO experiment_events"
            "(batch_id,ordinal,kind,detail,created)"
            " SELECT ?, COALESCE(MAX(ordinal),0)+1, 'recomputed', ?, ?"
            " FROM experiment_events WHERE batch_id=?",
            (identifier, json.dumps({"revision": revision}), created, identifier),
        )

    @staticmethod
    def _event(db, identifier, kind, detail, created):
        db.execute(
            "INSERT INTO experiment_events"
            "(batch_id,ordinal,kind,detail,created)"
            " SELECT ?, COALESCE(MAX(ordinal),0)+1, ?, ?, ?"
            " FROM experiment_events WHERE batch_id=?",
            (identifier, kind, json.dumps(detail, ensure_ascii=False), created,
             identifier),
        )

    @staticmethod
    def _state(db, identifier):
        row = db.execute(
            "SELECT revision,published FROM experiment_batches WHERE id=?",
            (identifier,),
        ).fetchone()
        if row is None:
            raise DomainIssue("RUN_NOT_FOUND")
        top = db.execute(
            "SELECT COALESCE(MAX(revision),0) AS top FROM experiment_decisions"
            " WHERE batch_id=?",
            (identifier,),
        ).fetchone()
        return {
            "revision": row["revision"],
            "published": bool(row["published"]),
            "max_revision": top["top"],
        }

    # -- 读取 --------------------------------------------------------------
    def load(self, identifier):
        with self.connect() as db:
            batch = db.execute(
                "SELECT * FROM experiment_batches WHERE id=?", (identifier,)
            ).fetchone()
            if batch is None:
                raise DomainIssue("RUN_NOT_FOUND")
            decision = db.execute(
                "SELECT * FROM experiment_decisions WHERE batch_id=? AND revision=?",
                (identifier, batch["revision"]),
            ).fetchone()
        return _shape(batch, decision)

    def load_revision(self, identifier, revision):
        with self.connect() as db:
            batch = db.execute(
                "SELECT * FROM experiment_batches WHERE id=?", (identifier,)
            ).fetchone()
            if batch is None:
                raise DomainIssue("RUN_NOT_FOUND")
            decision = db.execute(
                "SELECT * FROM experiment_decisions WHERE batch_id=? AND revision=?",
                (identifier, revision),
            ).fetchone()
        if decision is None:
            raise DomainIssue("REVISION_NOT_FOUND")
        return _shape(batch, decision)

    def history(self, identifier):
        with self.connect() as db:
            if db.execute(
                "SELECT 1 FROM experiment_batches WHERE id=?", (identifier,)
            ).fetchone() is None:
                raise DomainIssue("RUN_NOT_FOUND")
            active = db.execute(
                "SELECT revision FROM experiment_batches WHERE id=?", (identifier,)
            ).fetchone()["revision"]
            rows = db.execute(
                "SELECT revision,decision,reason,created,report"
                " FROM experiment_decisions WHERE batch_id=? ORDER BY revision",
                (identifier,),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["report"] = json.loads(item.pop("report"))
            item["active"] = item["revision"] == active
            result.append(item)
        return result

    def events(self, identifier):
        with self.connect() as db:
            if db.execute(
                "SELECT 1 FROM experiment_batches WHERE id=?", (identifier,)
            ).fetchone() is None:
                raise DomainIssue("RUN_NOT_FOUND")
            rows = db.execute(
                "SELECT ordinal,kind,detail,created FROM experiment_events"
                " WHERE batch_id=? ORDER BY ordinal",
                (identifier,),
            ).fetchall()
        return [
            {**dict(row), "detail": json.loads(row["detail"])} for row in rows
        ]

    def list(self):
        with self.connect() as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT id,created,updated,revision,published,decision"
                    " FROM (SELECT b.id,b.created,b.updated,b.revision,b.published,"
                    " d.decision FROM experiment_batches b"
                    " JOIN experiment_decisions d"
                    " ON d.batch_id=b.id AND d.revision=b.revision)"
                    " ORDER BY created DESC,id LIMIT 50"
                )
            ]


def _dump(report):
    return json.dumps(report, ensure_ascii=False, sort_keys=True)


def _shape(batch, decision):
    return {
        "id": batch["id"],
        "fingerprint": batch["fingerprint"],
        "rule_version": batch["rule_version"],
        "created": batch["created"],
        "updated": batch["updated"],
        "revision": batch["revision"],
        "published": bool(batch["published"]),
        "published_at": batch["published_at"],
        "status": decision["decision"],
        "reason": decision["reason"],
        "report": json.loads(decision["report"]),
    }
