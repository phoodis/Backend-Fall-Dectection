"""Measure what the live view costs: bytes per second, CPU, and how much it slows the detector.

Two roles, run as SEPARATE processes (the server runs them as separate processes too: the Flask app serves
the live view, the celery worker runs the detector loop):

    worker : runs the v3 detector loop (V3FallRunner, the profile camera_manager uses) on a clip, repeated,
             and reports frames processed per second.
    viewer : consumes generate_mjpeg_stream() like a browser would and reports MB/s, frames/s, JPEG size,
             and the CPU this process used per wall second.

    .venv-v3\\Scripts\\python.exe tools\\stream_bench.py worker --clip C:\\...\\Fall_6.mp4 --seconds 30
    .venv-v3\\Scripts\\python.exe tools\\stream_bench.py viewer --clip C:\\...\\Fall_6.mp4 --seconds 20 [--overlay]

--cores N pins the process to the first N logical CPUs (Windows), so a laptop with 16 threads can be made to
behave like a small server: pin worker and viewer to the SAME cores to see them compete. Run orchestration
(worker alone / worker + viewer) with tools/stream_bench_matrix.py. Numbers are for the machine they ran on.
"""
import argparse
import ctypes
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
os.environ.setdefault("V3_DEVICE", "cpu")


BUCKET_S = 2.0


def pin(cores):
    if not cores or os.name != "nt":
        return
    from ctypes import wintypes
    k32 = ctypes.windll.kernel32
    k32.GetCurrentProcess.restype = wintypes.HANDLE          # without these 64-bit handles are truncated
    k32.SetProcessAffinityMask.argtypes = [wintypes.HANDLE, ctypes.c_size_t]
    k32.SetProcessAffinityMask.restype = wintypes.BOOL
    if not k32.SetProcessAffinityMask(k32.GetCurrentProcess(), (1 << cores) - 1):
        sys.exit("could not pin the process to %d cores" % cores)


def run_worker(args):
    from app.services.camera_manager import V3FallRunner
    from app.services.model_manager import model_manager
    import torch
    det = model_manager.get_v3_fall_detector()
    if det is None:
        sys.exit("v3 detector could not be loaded")
    torch.set_num_threads(args.threads)
    # warm-up: the first frames include lazy initialisation
    for i, _ in enumerate(V3FallRunner.iter_video(det, args.clip, target_fps=8.0, realtime=False)):
        if i >= 8:
            break
    print("READY", flush=True)                       # the orchestrator starts the viewer on this line
    frames, cpu0, t0 = 0, time.process_time(), time.perf_counter()
    buckets = [0] * (int(args.seconds // BUCKET_S) + 1)   # frames per BUCKET_S-second slice
    while time.perf_counter() - t0 < args.seconds:
        for _ in V3FallRunner.iter_video(det, args.clip, target_fps=8.0, realtime=False):
            frames += 1
            buckets[min(int((time.perf_counter() - t0) // BUCKET_S), len(buckets) - 1)] += 1
            if time.perf_counter() - t0 >= args.seconds:
                break
    wall = time.perf_counter() - t0
    print(json.dumps({"role": "worker", "frames": frames, "wall_s": round(wall, 2),
                      "detector_fps": round(frames / wall, 2),
                      "bucket_fps": [round(b / BUCKET_S, 1) for b in buckets[:-1]],
                      "cpu_pct_of_one_core": round(100 * (time.process_time() - cpu0) / wall, 1)}), flush=True)


def load_legacy_stream_service():
    """The live view as it was before step 4 (git HEAD of the step-3 commit), for before/after runs."""
    import importlib.util
    import subprocess
    import tempfile
    src = subprocess.run(["git", "show", args_legacy_ref() + ":app/services/stream_service.py"],
                         capture_output=True, text=True, check=True, cwd=ROOT).stdout
    path = os.path.join(tempfile.mkdtemp(prefix="legacy_stream_"), "legacy_stream_service.py")
    open(path, "w", encoding="utf-8").write(src)
    spec = importlib.util.spec_from_file_location("legacy_stream_service", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def args_legacy_ref():
    return os.environ.get("STREAM_BENCH_LEGACY_REF", "497a519")


def run_viewer(args):
    if args.legacy:
        ss = load_legacy_stream_service()
        if args.no_person_detector:
            # as on a host where the person detector is not available: the old loop then runs unpaced
            from app.services.model_manager import model_manager
            model_manager.get_v2_person_detector = lambda: None
    else:
        from app.services import stream_service as ss
    kwargs = {}
    if args.overlay:
        kwargs["draw_overlay"] = True
    gen = ss.generate_mjpeg_stream(1, args.clip.replace("\\", "/"), "bench", **kwargs)
    # first chunk = stream start-up (opens the file, loads the pose model for the overlay); not counted
    next(gen)
    t0, cpu0 = time.perf_counter(), time.process_time()
    nbytes, frames = 0, 0
    for chunk in gen:
        if chunk:
            nbytes += len(chunk)
            frames += 1
        if time.perf_counter() - t0 >= args.seconds:
            break
    wall = time.perf_counter() - t0
    cpu = time.process_time() - cpu0
    ss.stream_manager.stop_stream(1)
    print(json.dumps({"role": "viewer", "legacy": bool(args.legacy), "overlay": bool(args.overlay), "wall_s": round(wall, 2), "frames": frames,
                      "view_fps": round(frames / wall, 2), "MB_per_s": round(nbytes / wall / 1e6, 3),
                      "KB_per_frame": round(nbytes / max(frames, 1) / 1e3, 1),
                      "cpu_pct_of_one_core": round(100 * cpu / wall, 1)}), flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("role", choices=["worker", "viewer"])
    ap.add_argument("--clip", required=True)
    ap.add_argument("--seconds", type=float, default=20)
    ap.add_argument("--threads", type=int, default=1, help="torch CPU threads for the worker (server: 1)")
    ap.add_argument("--cores", type=int, default=0, help="pin to the first N logical CPUs (0 = no pin)")
    ap.add_argument("--overlay", action="store_true")
    ap.add_argument("--legacy", action="store_true", help="use the live view as of commit 497a519 (before step 4)")
    ap.add_argument("--no-person-detector", action="store_true", help="with --legacy: person detector unavailable")
    args = ap.parse_args()
    pin(args.cores)
    (run_worker if args.role == "worker" else run_viewer)(args)


if __name__ == "__main__":
    main()
