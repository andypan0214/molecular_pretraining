#!/usr/bin/env bash
# Isolated, end-to-end 100-combination test of the NEW 250-CPU Stage 04.
# Usage: bash smoke_lipid_250cpu.sh [--submit | --status | --worker]
# Default: checks prerequisites, prints submission command, submits NOTHING.
set -Eeuo pipefail

PROJECT=/home/ypan/heart_liver/model_train/heart-molecular-pretraining
SCRIPTS="$PROJECT/model/pretrain/scripts/lipid_library"
ROOT=/home/ypan/heart_liver/model_train/lipid_library/smoke_250cpu
MAIN_ROOT=/home/ypan/heart_liver/model_train/lipid_library
PY=/home/ypan/.conda/envs/heart_gpu/bin/python
MODE="${1:---check}"

info() { printf '[smoke] %s\n' "$*"; }
fail() { printf '[smoke] ERROR: %s\n' "$*" >&2; exit 1; }

prerequisites() {
    [[ -f "$SCRIPTS/04_conformers_250cpu.sbatch" ]] || fail "New Stage 04 missing at $SCRIPTS/04_conformers_250cpu.sbatch"
    for script in 01_building_blocks.sh 03b_partition.sh 05_finalize.sh lipid_lib.sh; do
        [[ -f "$SCRIPTS/$script" ]] || fail "Missing $SCRIPTS/$script"
    done
    [[ -x "$PY" ]] || fail "Python environment missing: $PY"
    [[ -d "$PROJECT/model/pretrain/lipid_library" ]] || fail 'lipid_library Python package missing'
    [[ -f "$MAIN_ROOT/input/LUMI_virtual_library_training_lipidLike.xlsx" || \
       -f "$MAIN_ROOT/smoke_100/input/LUMI_virtual_library_training_lipidLike.xlsx" ]] || \
        fail "Input Excel not found in $MAIN_ROOT/input/ or smoke_100/input/. Copy the authorized source Excel to $MAIN_ROOT/input/."
}

if [[ "$MODE" == '--status' ]]; then
    [[ -f "$ROOT/job.id" ]] || fail "No saved smoke job ID at $ROOT/job.id"
    job_id="$(cat "$ROOT/job.id")"
    info "Job $job_id"
    squeue -j "$job_id" -o '%i %T %M %D %C' || true
    sacct -j "$job_id" --format=JobID,State,Elapsed,MaxRSS,AllocCPUS -P || true
    info "Logs: $ROOT/logs/"
    exit 0
fi

case "$MODE" in
    --check|--submit|--worker) ;;
    *) fail 'Usage: bash smoke_lipid_250cpu.sh [--check | --submit | --status]' ;;
esac

prerequisites

if [[ "$MODE" != '--worker' ]]; then
    command -v sbatch >/dev/null || fail 'sbatch unavailable'
    [[ ! -e "$ROOT/lmdb/manifest.json" ]] || fail "Completed smoke test exists at $ROOT; refusing to overwrite"
    info "New isolated output: $ROOT"
    info 'Only 100 Ugi combinations; 4 CPU workers, 16 GB RAM, GPU partition (1 GPU allocated but unused).'
    info 'Runs building blocks, 100-combination enumeration, dedup, NEW 03b, NEW 04, and NEW 05.'
    info 'Does NOT submit 15M production, does NOT use the 250-CPU allocation.'
    info 'New Stage 04 will be executed inside a real SLURM compute allocation.'
    if [[ "$MODE" == '--check' ]]; then
        info "Ready. To submit: bash $(basename "$0") --submit"
        exit 0
    fi
    # SLURM output file parent must exist before sbatch starts.
    mkdir -p "$ROOT/logs"
    # Do not let preexisting production/smoke variables contaminate the run.
    job_id="$(sbatch --parsable --partition=gpu --nodes=1 --ntasks=1 \
        --cpus-per-task=4 --mem=16G --gres=gpu:1 --time=02:00:00 \
        --job-name=lipid-smoke-new04 \
        --output="$ROOT/logs/smoke-%j.out" --error="$ROOT/logs/smoke-%j.err" \
        --export=ALL "$0" --worker)"
    printf '%s\n' "$job_id" > "$ROOT/job.id"
    info "Submitted SMOKE job: $job_id (not production)"
    info "Monitor: squeue -j $job_id"
    info "Logs: tail -f $ROOT/logs/smoke-$job_id.out"
    exit 0
fi

[[ -n "${SLURM_JOB_ID:-}" ]] || fail 'Worker mode must run under SLURM; no login-node RDKit computation allowed'
[[ "${SLURM_CPUS_PER_TASK:-}" == 4 ]] || fail 'This smoke worker requires exactly 4 allocated CPUs'

# Strict isolation: prevent ambient production configuration from leaking through sbatch --export=ALL.
unset SLURM_ARRAY_TASK_ID SLURM_ARRAY_TASK_COUNT SLURM_ARRAY_TASK_MAX
unset LIMIT LIPID_LMDB_DIR LIPID_ARRAY_SIZE LIPID_ENUM_ARRAY_SIZE LIPID_WORKERS RECORDS_PER_SHARD CHUNK_SIZE
unset STORE_2D HEART_CONFIRM_LIPID VALID_SHARDS VALID_FRACTION SEED_START MAX_ATOMS SEC_PER_MOLECULE
export LIPID_ROOT="$ROOT"
export LIPID_INPUT="$MAIN_ROOT/input/LUMI_virtual_library_training_lipidLike.xlsx"
if [[ ! -f "$LIPID_INPUT" ]]; then
    LIPID_INPUT="$MAIN_ROOT/smoke_100/input/LUMI_virtual_library_training_lipidLike.xlsx"
    export LIPID_INPUT
fi
export HEART_CONFIRM_LIPID=1 STORE_2D=0
export LIMIT=100 CHUNK_SIZE=100 RECORDS_PER_SHARD=10
export LIPID_ARRAY_SIZE=4 LIPID_WORKERS=4 VALID_SHARDS=1
export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
export PYTHONPATH="$PROJECT/model/pretrain${PYTHONPATH:+:$PYTHONPATH}"

[[ "$ROOT" != "$MAIN_ROOT" && "$ROOT" != "$MAIN_ROOT/smoke_100" ]] || fail 'Unsafe output path'
mkdir -p "$ROOT/logs"
cd "$PROJECT/model/pretrain"

info 'Stage 01: building blocks + review'
bash "$SCRIPTS/01_building_blocks.sh"
[[ -f "$ROOT/bb/building_blocks.csv" ]] || fail 'Stage 01 failed to create building_blocks.csv'

info 'Stage 02 SMOKE: exactly 100 combinations, not full enumeration'
"$PY" -m lipid_library.enumerate_library "$ROOT/bb" -o "$ROOT/enum" \
    --limit 100 --chunk-size 100
"$PY" -m lipid_library.enumerate_library "$ROOT/bb" -o "$ROOT/enum" \
    --limit 100 --chunk-size 100 --check-complete

info 'Stage 03 SMOKE: duplicate detection'
mkdir -p "$ROOT/tmp"
"$PY" -m lipid_library.dedup "$ROOT/enum" -o "$ROOT/dedup" \
    --tmp-dir "$ROOT/tmp" --require-complete
[[ -f "$ROOT/dedup/drop_combo_indexes.csv.gz" ]] || fail 'Deduplication drop list missing'

info 'Stage 03b: REAL updated partition script'
bash "$SCRIPTS/03b_partition.sh"
[[ -f "$ROOT/lmdb/shard_inputs/partition_index.json" ]] || fail 'Partition index missing'

info 'Stage 04: REAL new multiprocessing script, running 4 workers in SLURM allocation'
# The script uses $LIPID_ARRAY_SIZE as stride and $LIPID_WORKERS as xargs -P.
bash "$SCRIPTS/04_conformers_250cpu.sbatch"

info 'Stage 05: REAL updated finalization and validation script'
bash "$SCRIPTS/05_finalize.sh"

info 'Verify manifest, splits, and validation artifacts'
"$PY" - "$ROOT" <<'PY'
import json, pathlib, sys
root=pathlib.Path(sys.argv[1])
lmdb=root/'lmdb'
for filename in ('manifest.json','splits.json','validation.json','finalize_report.json'):
    p=lmdb/filename
    if not p.is_file():
        raise SystemExit('MISSING final artifact: '+str(p))
    print('FOUND',p)
manifest=json.loads((lmdb/'manifest.json').read_text())
splits=json.loads((lmdb/'splits.json').read_text())
if not manifest.get('complete') or not manifest.get('smoke'):
    raise SystemExit('Manifest is not a complete isolated smoke dataset')
if not splits.get('complete') or not splits.get('smoke'):
    raise SystemExit('Splits are not marked complete/smoke')
if manifest.get('stored_2d_conformer'):
    raise SystemExit('Unexpected stored 2D conformer')
if manifest.get('coordinate_slots_per_record') != 10:
    raise SystemExit('Expected 10 stored 3D slots')
print('SMOKE PASSED:',len(manifest['shards']),'LMDB shards;',
      sum(s['n_records'] for s in manifest['shards']),'records')
print('Train / valid records:',splits['n_records'])
PY
info "SMOKE TEST PASSED. Outputs preserved at: $ROOT"
