#!/usr/bin/env bash
# Step 1 benchmark runner - single entry point.
#   - never touches the running backend/celery/db containers
#   - isolated venv under ~/apps/bench (created if missing)
#   - torch pinned to the CPU wheel index (no CUDA download)
#   - pinned to 2 cores via taskset
#   - df -h before AND after dependency install
#   - 3 rounds per model, all in this one script
set -euo pipefail

VIDEO_PATH="${1:?Usage: run_benchmark.sh /path/to/test_fall.mp4 [bench_dir]}"
BENCH_DIR="${2:-$HOME/apps/bench}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== disk space BEFORE install ==="
df -h

mkdir -p "$BENCH_DIR"
if [ ! -d "$BENCH_DIR/venv" ]; then
    python3 -m venv "$BENCH_DIR/venv"
fi
# shellcheck disable=SC1091
source "$BENCH_DIR/venv/bin/activate"

pip install --upgrade pip
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
# mediapipe + pytest installed now too: Step 2 (gate) and the test suite
# reuse this same venv, so we only pay the install cost once.
pip install ultralytics opencv-python-headless mediapipe pytest "numpy<2.0.0"

echo "=== disk space AFTER install ==="
df -h

mkdir -p "$BENCH_DIR/results"
cp "$SCRIPT_DIR/benchmark_models.py" "$BENCH_DIR/benchmark_models.py"

echo "=== running benchmark (2 cores pinned via taskset -c 0,1) ==="
taskset -c 0,1 python "$BENCH_DIR/benchmark_models.py" \
    --video "$VIDEO_PATH" \
    --runs 3 \
    --out "$BENCH_DIR/results/benchmark_report.md" \
    --json-out "$BENCH_DIR/results/benchmark_report.json"

echo ""
echo "Report written to: $BENCH_DIR/results/benchmark_report.md"
