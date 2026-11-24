"""实验判定单证据包。

导出当前生效判定，同时附带完整的不可变版本链，确保旧版决策证据始终可追溯。
"""

import json


def artifact(batch, history=None, events=None):
    packet = {
        "schema": "experiment-evidence/1",
        "batch": {
            key: batch[key]
            for key in ("id", "fingerprint", "rule_version", "created", "updated",
                        "revision", "published", "published_at", "status", "reason")
        },
        "report": batch["report"],
        "versions": [
            {
                "revision": item["revision"],
                "active": item["active"],
                "decision": item["decision"],
                "reason": item["reason"],
                "created": item["created"],
                "report": item["report"],
            }
            for item in (history or [])
        ],
        "events": events or [],
    }
    return (
        json.dumps(packet, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode()
