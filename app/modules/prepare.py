from app.business import DomainIssue, by_kind, prepared, single


def prepare(rows):
    event = single(rows, "conversion")
    target = single(rows, "expected")["value_cents"]
    t = event["minute"]
    valid = [
        r
        for r in by_kind(rows, "touch")
        if r["consent"] == 1 and t - event["lookback"] <= r["minute"] < t
    ]
    if not valid:
        raise DomainIssue("NO_TOUCH")
    return prepared(
        len(valid),
        {"conversion_min": t, "lookback_min": event["lookback"]},
        (event, valid, target),
    )
