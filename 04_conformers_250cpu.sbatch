#!/usr/bin/env bash
#SBATCH --partition=gpu
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=250
#SBATCH --mem=500G
#SBATCH --gres=gpu:1
#SBATCH --time=2-00:00:00
#SBATCH --job-name=lipid-04-250cpu
#SBATCH --output=/home/ypan/heart_liver/model_train/lipid_library/logs/%x-%j.out
#SBATCH --error=/home/ypan/heart_liver/model_train/lipid_library/logs/%x-%j.err
# Stage 04: one H200-node allocation running many single-core RDKit workers.
# The GPU is reserved only because the validated gpu-partition allocation uses it;
# RDKit work does not use CUDA. Not optimized or benchmarked on CMRI yet.
# Requires completed Stages 01, 02, 03, 03b, and matching partition_index.json.
# Never run this concurrently with 04_conformers_array.sh on the same output.
set -Eeuo pipefail

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
if [[ ! -r "$HERE/lipid_lib.sh" ]]; then
  HERE=/home/ypan/heart_liver/model_train/heart-molecular-pretraining/model/pretrain/scripts/lipid_library
fi
# shellcheck disable=SC1091
source "$HERE/lipid_lib.sh"
lipid_init "$HERE/04_conformers_250cpu.sbatch"
lipid_writer_args

[[ -f "$LIPID_DEDUP/drop_combo_indexes.csv.gz" ]] || die 'Stage 03 missing'
[[ -r "$LIPID_LMDB/shard_inputs/partition_index.json" ]] || die 'Stage 03b missing'
[[ -r "$LIPID_DICT" ]] || die 'HEART dictionary missing'
[[ "${STORE_2D:-}" == 0 ]] || die 'This pipeline requires STORE_2D=0'

# Keep the original 1000-way stride so Stage 05 and resubmission mapping stay compatible.
STRIDE="${LIPID_ARRAY_SIZE:-1000}"
WORKERS="${LIPID_WORKERS:-250}"
[[ "$STRIDE" =~ ^[1-9][0-9]*$ && "$WORKERS" =~ ^[1-9][0-9]*$ ]] || die 'Bad stride/worker count'
[[ "$WORKERS" -le "${SLURM_CPUS_PER_TASK:-250}" ]] || die 'Workers exceed allocated CPUs'
[[ "$WORKERS" -le 250 ]] || die 'At most 250 workers are supported here'

# Protect the entire output from accidental overlapping 04 jobs.
command -v flock >/dev/null || die 'flock is required'
mkdir -p "$LIPID_LMDB"
exec 9>"$LIPID_LMDB/.stage04_parallel.lock"
flock -n 9 || die 'Another 04 parallel run holds the stage04 lock; stop'

# Fail closed on scientific / partition mismatches BEFORE spawning workers.
plan_json="$("$PY" -m lipid_library.lmdb_writer "$LIPID_ENUM" -o "$LIPID_LMDB" \
  "${LIPID_WRITER_ARGS[@]}" --plan --array-size "$STRIDE")"
"$PY" - "$plan_json" <<'PY'
import json, sys
plan=json.loads(sys.argv[1])
assert plan.get('partition')=='matches', f"Stage 03b partition mismatch: {plan.get('partition')}"
assert plan['n_shards']>0, 'No shards to generate'
print(f"INPUT: {plan['n_rows']:,} molecules; {plan['n_shards']:,} shards")
PY

# Initialize both atomic config locks in one process to avoid concurrent read-before-write.
"$PY" - "$LIPID_ENUM" "$LIPID_LMDB" "${LIPID_WRITER_ARGS[@]}" --num-shards "$STRIDE" <<'PY'
import sys
from lipid_library.lmdb_writer import build_parser, writer_config, lock_array_geometry, load_partition
from lipid_library import provenance
ns = build_parser().parse_args([sys.argv[1], '-o', sys.argv[2], *sys.argv[3:]])
load_partition(ns.out_dir, ns, ns.products_dir)
provenance.lock_config(ns.out_dir, 'lmdb_writer', writer_config(ns, ns.products_dir))
lock_array_geometry(ns.out_dir, ns.num_shards)
print('Configuration and array-geometry locks verified')
PY

printf 'JOB=%s NODE=%s CPUs=%s RAM=500G RDKit_WORKERS=%s STRIDE=%s\n' \
  "${SLURM_JOB_ID:-local}" "$(hostname)" "${SLURM_CPUS_PER_TASK:-unknown}" "$WORKERS" "$STRIDE"
export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
# GNU xargs manages a bounded process pool. Each process handles shards s % STRIDE == task_id.
# The writer verifies receipts and skips completed shards on re-submission.
seq 0 "$((STRIDE - 1))" | xargs -P "$WORKERS" -n 1 \
  "$PY" -m lipid_library.lmdb_writer "$LIPID_ENUM" -o "$LIPID_LMDB" \
  "${LIPID_WRITER_ARGS[@]}" --map-size-gb 64 --commit-every 2000 \
  --num-shards "$STRIDE" --shard

echo 'Stage 04 finished successfully. Stage 05 may now finalize the library.'
