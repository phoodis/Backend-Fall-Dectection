"""Run the scenarios of tools/stream_bench.py one after another and print one table.

    .venv-v3\\Scripts\\python.exe tools\\stream_bench_matrix.py --clip C:\\...\\Fall_6.mp4 --cores 2 [--overlay]

Scenarios (worker and viewer are separate processes pinned to the same --cores, like a small server):
    worker alone | viewer alone | worker + viewer | (with --overlay) viewer with overlay alone, worker + overlay viewer
The detector fps "during the view" is the mean of its 2-second slices in the middle half of the run, so the
viewer start-up and tail do not count. Worker scenarios run round-robin --repeats times.
"""
import argparse
import json
import os
import statistics
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
BENCH = os.path.join(HERE, "stream_bench.py")


def start(role, args, extra=()):
    cmd = [PY, BENCH, role, "--clip", args.clip, "--cores", str(args.cores)] + list(extra)
    env = dict(os.environ)
    if role == "worker":
        env["OMP_NUM_THREADS"] = "1"          # docker-compose.yml sets this on celery_worker only
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True, cwd=os.path.dirname(HERE), env=env)


def last_json(proc):
    out = proc.communicate()[0]
    for line in reversed(out.strip().splitlines()):
        if line.startswith("{"):
            return json.loads(line)
    raise SystemExit(f"no result from {proc.args}:\n{out}")


def viewer(args, kind):
    """kind: 'legacy' | 'legacy-nodet' | 'new' | 'overlay'"""
    extra = ["--seconds", str(args.view_seconds)]
    if kind.startswith("legacy"):
        extra.append("--legacy")
    if kind == "legacy-nodet":
        extra.append("--no-person-detector")
    if kind == "overlay":
        extra.append("--overlay")
    return start("viewer", args, extra)


def worker_with(args, kind):
    w = start("worker", args, ["--seconds", str(args.worker_seconds), "--threads", str(args.threads)])
    while True:                                   # wait for the worker's model to be loaded and warm
        line = w.stdout.readline()
        if line.strip() == "READY" or not line:
            break
    v = viewer(args, kind) if kind is not None else None
    wr = last_json(w)
    vr = last_json(v) if v else None
    return wr, vr


def middle_fps(w):
    """Mean fps over the middle half of the run, so the viewer's start-up and tail do not count."""
    b = w["bucket_fps"]
    mid = b[len(b) // 4: len(b) - len(b) // 4] or b
    return round(sum(mid) / len(mid), 2)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--clip", required=True)
    ap.add_argument("--cores", type=int, default=4)
    ap.add_argument("--threads", type=int, default=1)
    ap.add_argument("--worker-seconds", type=float, default=36)
    ap.add_argument("--view-seconds", type=float, default=20)
    ap.add_argument("--repeats", type=int, default=3, help="worker scenarios are run round-robin this many times")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    res = {"viewer alone": {}, "worker": {}}
    for kind in ("legacy", "legacy-nodet", "new", "overlay"):
        res["viewer alone"][kind] = last_json(viewer(args, kind))
    scenarios = [None, "legacy", "new", "overlay"]
    for s in scenarios:
        res["worker"][str(s)] = {"detector_fps": [], "viewer": []}
    for _ in range(args.repeats):
        for s in scenarios:
            w, v = worker_with(args, s)
            res["worker"][str(s)]["detector_fps"].append(middle_fps(w))
            if v:
                res["worker"][str(s)]["viewer"].append(v)
    print(json.dumps(res, indent=1))
    if args.out:
        json.dump(res, open(args.out, "w"), indent=1)


if __name__ == "__main__":
    main()
