"""Replay labelled clips through the v3 loop that camera_manager.py runs (V3FallRunner + the detector
from model_manager) and compare with a reference evaluation (per-frame CSVs + predictions CSV written
by the evaluation harness this detector was measured with).

    .venv-v3\\Scripts\\python.exe tools\\v3_eval_via_camera_manager.py ^
        --dataset "C:\\...\\Dataset_clips" ^
        --reference C:\\Users\\ASUS\\FALL_DETECT\\eval\\results ^
        --predictions-csv C:\\Users\\ASUS\\FALL_DETECT\\eval\\results\\predictions_v2.csv

For every clip x mode it checks, against the reference: identical frame indices, per-frame probability
(max / mean absolute difference), per-frame fall flag and person count, and the clip-level row
(pred_label, fall_frames, first_fall_time, max_conf). Exit code 1 if anything differs.

Modes: deployed8fps = file sampled at 8 fps by source time (what the camera loop does);
       allframes    = every decoded frame (V3 target fps 0).
"""
import argparse
import csv
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("V3_DEVICE", "cpu")          # the evaluation ran on CPU
os.chdir(ROOT)                                      # model dir 'models' is relative

MODES = {"deployed8fps": 8.0, "allframes": 0.0}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", required=True, help="folder with the clips and labels.csv")
    ap.add_argument("--labels", default=None, help="default: <dataset>/labels.csv (only clip_id is used)")
    ap.add_argument("--reference", required=True, help="reference results folder (contains frames/own/*.csv)")
    ap.add_argument("--predictions-csv", required=True, help="reference predictions CSV (set,mode,clip,...)")
    ap.add_argument("--modes", default="deployed8fps,allframes")
    ap.add_argument("--clips", default=None, help="comma-separated clip stems, default: all in labels.csv")
    ap.add_argument("--out", default=os.path.join(ROOT, "results", "v3_parity"))
    ap.add_argument("--threads", type=int, default=4, help="torch CPU threads (speed only)")
    ap.add_argument("--tol", type=float, default=0.0, help="max allowed |delta prob| (default exact)")
    args = ap.parse_args()

    labels = args.labels or os.path.join(args.dataset, "labels.csv")
    with open(labels, encoding="utf-8-sig", newline="") as fh:
        clips = [r["clip_id"] for r in csv.DictReader(fh)]
    if args.clips:
        keep = set(args.clips.split(","))
        clips = [c for c in clips if os.path.splitext(c)[0] in keep]
    modes = [m for m in args.modes.split(",") if m]
    os.makedirs(args.out, exist_ok=True)

    ref_pred = {}
    with open(args.predictions_csv, newline="") as fh:
        for r in csv.DictReader(fh):
            if r["set"] == "own":
                ref_pred[(r["mode"], r["clip"])] = r

    from app.services.camera_manager import V3FallRunner      # the code under test
    from app.services.model_manager import model_manager
    import torch
    det = model_manager.get_v3_fall_detector()
    if det is None:
        sys.exit("v3 detector could not be loaded")
    torch.set_num_threads(args.threads)                        # after the model is built, as the evaluation did
    from app.detection import v3_fall_detection as v3
    print("identity:", v3.LOADED_IDENTITY, flush=True)

    summary, bad = {}, 0
    for mode in modes:
        for clip in clips:
            stem = os.path.splitext(clip)[0]
            rows = []
            for index, fps, frame, results, top, runner in V3FallRunner.iter_video(
                    det, os.path.join(args.dataset, clip), target_fps=MODES[mode], realtime=False):
                _, detected, prob, label, _ = top
                rows.append({"frame": index, "time_s": index / fps, "n_people": runner.state.seen_count,
                             "fall": bool(detected), "prob": float(prob), "label": label})
            with open(os.path.join(args.out, f"{stem}__{mode}.csv"), "w", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=list(rows[0]))
                w.writeheader()
                w.writerows(rows)

            ref = []
            with open(os.path.join(args.reference, "frames", "own", f"{stem}__{mode}.csv"), newline="") as fh:
                for r in csv.DictReader(fh):
                    ref.append({"frame": int(r["frame"]), "n_people": int(r["n_people"]), "fall": r["fall"] == "True",
                                "prob": float(r["prob"]), "label": r["label"]})
            same_idx = [r["frame"] for r in rows] == [r["frame"] for r in ref]
            n = min(len(rows), len(ref))
            d = [abs(rows[i]["prob"] - ref[i]["prob"]) for i in range(n)]
            flag_mis = sum(1 for i in range(n) if rows[i]["fall"] != ref[i]["fall"])
            ppl_mis = sum(1 for i in range(n) if rows[i]["n_people"] != ref[i]["n_people"])
            lab_mis = sum(1 for i in range(n) if rows[i]["label"] != ref[i]["label"])

            fall_rows = [r for r in rows if r["fall"]]
            mine = {"pred_label": str(int(bool(fall_rows))), "fall_frames": str(len(fall_rows)),
                    "first_fall_time": str(round(fall_rows[0]["time_s"], 3)) if fall_rows else "",
                    "max_conf": str(round(max(r["prob"] for r in rows), 4))}
            rp = ref_pred.get((mode, clip))
            row_ok = rp is not None and all(str(rp[k]) == v for k, v in mine.items())
            ok = (same_idx and len(rows) == len(ref) and (max(d) if d else 0) <= args.tol and flag_mis == 0
                  and ppl_mis == 0 and lab_mis == 0 and row_ok)
            bad += (not ok)
            summary[f"{mode}/{clip}"] = {
                "ok": ok, "frames": len(rows), "frames_ref": len(ref), "same_frame_indices": same_idx,
                "max_abs_dprob": max(d) if d else None, "mean_abs_dprob": sum(d) / len(d) if d else None,
                "fall_flag_mismatch": flag_mis, "n_people_mismatch": ppl_mis, "label_mismatch": lab_mis,
                "clip_row": mine, "clip_row_ref": ({k: rp[k] for k in mine} if rp else None), "clip_row_equal": row_ok}
            print(f"[{'OK ' if ok else 'DIFF'}] {mode:13s} {clip:14s} frames={len(rows):6d} "
                  f"max|dp|={max(d) if d else 0:.3g} flag_mis={flag_mis} ppl_mis={ppl_mis} "
                  f"pred={mine['pred_label']} fall_frames={mine['fall_frames']} first={mine['first_fall_time'] or '-'} "
                  f"clip_row_equal={row_ok}", flush=True)
            json.dump(summary, open(os.path.join(args.out, f"summary_{'_'.join(modes)}.json"), "w"), indent=1)
    print(f"\n{len(summary) - bad}/{len(summary)} clip x mode results identical to the reference")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
