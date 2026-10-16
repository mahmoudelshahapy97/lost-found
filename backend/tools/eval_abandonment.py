# tools/eval_abandonment.py
"""Score the abandonment pipeline against hand-labelled clips.

Runs the same ObjectTracker + AbandonmentTracker the camera workers use over
every clip in a folder, at the worker's processing rate, and compares the
alerts with ground truth (tools/abandonment_gt.json):

    true positive   an alert within --match-px of a labelled item, raised after
                    its owner walked away
    false alarm     any other alert
    missed          a labelled item with no matching alert

Each clip is played --loops times back to back with continuous timestamps,
the way the looping test streams reach the cameras; ground truth repeats in
every loop. Loops matter: state carried from one pass into the next (an item
already there when someone walks by) is where live false alarms came from.

    python tools/eval_abandonment.py --videos /videos --set abandon_seconds=5 --loops 3

Run inside the api container (it needs the model and the GPU).
"""

import argparse
import json
import math
import os
import sys
import time

import cv2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import config  # noqa: E402
from app.services.abandonment_service import AbandonmentParams, AbandonmentTracker  # noqa: E402
from app.services.tracking_service import ObjectTracker  # noqa: E402


def parse_overrides(pairs):
    overrides = {}
    for pair in pairs or []:
        key, _, value = pair.partition("=")
        overrides[key] = float(value)
    return overrides


def run_clip(path, params, model, loops=1):
    """Alerts over ``loops`` back-to-back plays, and the length of one play in seconds."""
    tracker = ObjectTracker(model)
    machine = AbandonmentTracker(params=AbandonmentParams.from_settings(params))
    alerts, index, duration = [], 0, 0.0
    for _ in range(loops):
        capture = cv2.VideoCapture(path)
        fps = capture.get(cv2.CAP_PROP_FPS) or 25.0
        stride = max(1, round(fps / config.target_process_fps))
        start = index
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            index += 1
            if index % stride:
                continue
            timestamp = index / fps
            for event in machine.update(tracker.track(frame), timestamp):
                x1, y1, x2, y2 = event.box
                alerts.append({"t": timestamp, "at": ((x1 + x2) / 2, (y1 + y2) / 2), "class": event.class_name})
        duration = (index - start) / fps
        capture.release()
    return alerts, duration


def score(alerts, truth, match_px):
    hits, false_alarms, claimed = [], [], set()
    for alert in alerts:
        match = next(
            (
                i
                for i, item in enumerate(truth)
                if i not in claimed
                and math.dist(alert["at"], item["at"]) <= match_px
                and alert["t"] >= item["unattended_from"]
            ),
            None,
        )
        if match is None:
            # A second alert on an item already caught is a duplicate, not a hit.
            near_claimed = any(math.dist(alert["at"], truth[i]["at"]) <= match_px for i in claimed)
            false_alarms.append({**alert, "duplicate": near_claimed})
        else:
            claimed.add(match)
            hits.append({**alert, "delay": alert["t"] - truth[match]["unattended_from"]})
    missed = [item for i, item in enumerate(truth) if i not in claimed]
    return hits, false_alarms, missed


def main() -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--videos", required=True, help="folder holding the labelled clips")
    parser.add_argument("--gt", default=os.path.join(here, "abandonment_gt.json"))
    parser.add_argument("--set", action="append", metavar="KEY=VALUE", help="AbandonmentParams override")
    parser.add_argument("--match-px", type=float, default=70.0)
    parser.add_argument("--loops", type=int, default=1, help="plays of each clip, back to back")
    args = parser.parse_args()

    from ultralytics import YOLO

    truth_by_clip = {k: v for k, v in json.load(open(args.gt)).items() if not k.startswith("_")}
    params = parse_overrides(args.set)
    model = YOLO(config.yolo_model_path)

    totals = {"hits": 0, "false": 0, "missed": 0, "items": 0}
    started = time.time()
    for clip, truth in sorted(truth_by_clip.items()):
        path = os.path.join(args.videos, clip)
        if not os.path.exists(path):
            print(f"{clip:30s} skipped (not found)")
            continue
        alerts, duration = run_clip(path, params, model, args.loops)
        # The items are left again in every loop.
        looped = [
            {**item, "unattended_from": item["unattended_from"] + k * duration}
            for k in range(args.loops)
            for item in truth
        ]
        hits, false_alarms, missed = score(alerts, looped, args.match_px)
        totals["hits"] += len(hits)
        totals["false"] += len(false_alarms)
        totals["missed"] += len(missed)
        totals["items"] += len(looped)
        detail = []
        detail += ["HIT +%.0fs" % h["delay"] for h in hits]
        detail += ["FALSE %s@(%d,%d)%s" % (f["class"], *f["at"], " dup" if f["duplicate"] else "") for f in false_alarms]
        detail += ["MISSED (%d,%d)" % tuple(m["at"]) for m in missed]
        print(f"{clip:30s} {', '.join(detail) or 'ok (no items, no alerts)'}")

    precision = totals["hits"] / max(1, totals["hits"] + totals["false"])
    recall = totals["hits"] / max(1, totals["items"])
    print(
        f"\nparams={params or 'defaults'}  items={totals['items']}  hits={totals['hits']}  "
        f"false_alarms={totals['false']}  missed={totals['missed']}  "
        f"precision={precision:.2f}  recall={recall:.2f}  ({time.time() - started:.0f}s)"
    )


if __name__ == "__main__":
    main()
