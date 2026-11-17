"""When each workflow step could start if instruments worked at the same time.

The workflow is saved as one ordered list and the mock contract runs it one step after
another. Here every step keeps that order on the things it uses, and starts as soon as
they are all free: its sample, its instrument, and for a transfer the arm and both
instruments it moves between. Two samples on two instruments then overlap.

A planning estimate only: nothing runs steps side by side, and slots are not rechecked.
"""


def schedule(steps, trace, motions):
    """[{step, start_s, end_s}] in workflow order, and the time the last step ends."""
    arm = {m["step"]: m["seconds"] for m in motions}
    free, rows, before = {}, [], 0.0
    for step, entry in zip(steps, trace, strict=True):
        lasts = arm.get(entry["step"], entry["elapsed_s"] - before)
        before = entry["elapsed_s"]
        uses = {("sample", entry["sample"]), ("device", step["device_id"])}
        if step["operation"] == "transfer":
            uses |= {("device", step["source_id"]), ("device", step["target_id"])}
        start = max((free.get(u, 0.0) for u in uses), default=0.0)
        for u in uses:
            free[u] = start + lasts
        rows.append(
            {"step": entry["step"], "start_s": round(start, 1), "end_s": round(start + lasts, 1)}
        )
    return rows, round(max((r["end_s"] for r in rows), default=0.0), 1)
