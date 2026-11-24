from app.business import measured


def compute(data):
    event, valid, target = data
    chosen = max(valid, key=lambda r: (bool(r["channel"]), r["minute"], r["record"]))
    return measured(
        event["value_cents"],
        target,
        "分",
        {
            "channel": chosen["channel"],
            "chosen_touch": chosen["record"],
            "elapsed_min": event["minute"] - chosen["minute"],
        },
    )
