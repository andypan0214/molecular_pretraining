#!/usr/bin/env bash
# Submit the EXISTING HEART lipid-library stages as REAL SLURM jobs.
# 01 -> 02 (64-task array) -> 03 -> 03b -> 04 (H200/250 CPU) -> 05.
# This is a submission wrapper: run on a login node. It does not run RDKit locally.
# No dry-run; executing this file submits jobs immediately.
set -Eeuo pipefail

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
ROOT=/home/ypan/heart_liver/model_train/lipid_library
INPUT="${LIPID_INPUT:-$ROOT/input/LUMI_virtual_library_training_lipidLike.xlsx}"
CPU_PARTITION="${CPU_PARTITION:-gpu}"   # Original stages run CPU-only on this partition.
GPU_PARTITION=gpu
H200_GRES="${H200_GRES:-gpu:h200:1}"  # Previously accepted on CMRI; NOT gpu:h200a:1.
H200_NODE="${H200_NODE:-cmri-gpu04}"   # Change to cmri-gpu05 or empty to allow either.
STAGE04_CPUS=250
STAGE04_WORKERS=250
STAGE04_MEM=500G
STAGE04_TIME=2-00:00:00

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 2; }
[[ $# == 0 ]] || fail 'Usage: bash submit_lipid_library_production_now.sh (no arguments)'
[[ -z "${LIMIT:-}" ]] || fail 'Unset LIMIT: production must not use the smoke limit'
[[ "${LIPID_ROOT:-$ROOT}" == "$ROOT" ]] || fail 'LIPID_ROOT points outside the expected production directory'
[[ "${LIPID_ARRAY_SIZE:-1000}" == 1000 ]] || fail 'LIPID_ARRAY_SIZE must be 1000 for production'
[[ -r "$INPUT" ]] || fail "Missing source Excel: $INPUT"
command -v sbatch >/dev/null || fail 'sbatch command unavailable'
command -v flock >/dev/null || fail 'flock command unavailable'
for file in 01_building_blocks.sh 02_enumerate_array.sh 03_dedup.sh 03b_partition.sh 04_conformers_250cpu.sbatch 05_finalize.sh lipid_lib.sh; do
  [[ -r "$HERE/$file" ]] || fail "Missing $HERE/$file"
done
[[ ! -e "$ROOT/lmdb/manifest.json" ]] || fail 'Production manifest exists: library may already be complete; inspect before submitting'
mkdir -p "$ROOT/logs"
exec 9>"$ROOT/logs/.submission_lock"
flock -n 9 || fail 'Another production submission is in progress'
RECORD="$ROOT/logs/production_stage_jobs.tsv"
[[ ! -e "$RECORD" ]] || fail "Existing submission record $RECORD. Inspect current jobs before another submission."
printf 'stage\tjob_id\tdependency\tresources\n' > "$RECORD"

# Critical scientific settings are kept identical across 03b, 04, 05.
EXPORT="ALL,HEART_CONFIRM_LIPID=1,STORE_2D=0,LIPID_ROOT=$ROOT,LIPID_INPUT=$INPUT,LIPID_ARRAY_SIZE=1000,LIPID_ENUM_ARRAY_SIZE=64,LIPID_WORKERS=$STAGE04_WORKERS"

submit_stage() {
  local label="$1" dependency="$2" file="$3" array="$4" cpus="$5" mem="$6" wall="$7" resource_class="$8"
  local -a cmd=(sbatch --parsable --nodes=1 --ntasks=1 "--cpus-per-task=$cpus" "--mem=$mem" "--time=$wall" "--export=$EXPORT")
  if [[ "$resource_class" == h200 ]]; then
    cmd+=("--partition=$GPU_PARTITION" "--gres=$H200_GRES")
    [[ -z "$H200_NODE" ]] || cmd+=("--nodelist=$H200_NODE")
  else
    cmd+=("--partition=$CPU_PARTITION")
    # Intentionally do NOT request a GPU for CPU-only stages.
  fi
  [[ -z "$dependency" ]] || cmd+=("--dependency=$dependency")
  [[ -z "$array" ]] || cmd+=("--array=$array")
  if [[ -z "$array" ]]; then
    cmd+=("--output=$ROOT/logs/%x-%j.out" "--error=$ROOT/logs/%x-%j.err")
  else
    cmd+=("--output=$ROOT/logs/%x-%A_%a.out" "--error=$ROOT/logs/%x-%A_%a.err")
  fi
  cmd+=("$HERE/$file")
  local result id
  result="$("${cmd[@]}")" || fail "Stage $label sbatch rejected. Earlier stages may already have been submitted; inspect $RECORD before retrying."
  id="${result%%;*}"
  [[ "$id" =~ ^[0-9]+$ ]] || fail "Unexpected sbatch response for $label: $result"
  printf '%s\t%s\t%s\t%s\n' "$label" "$id" "${dependency:-none}" "$cpus CPU, $mem, $resource_class" >> "$RECORD"
  printf 'SUBMITTED Stage %-3s Job %s\n' "$label" "$id" >&2
  REPLY="$id"
}

# Real submissions (no --test-only, no dry-run).
submit_stage 01  ''                   01_building_blocks.sh       ''         1   4G    00:30:00  cpu;  j01=$REPLY
submit_stage 02  "afterok:$j01"       02_enumerate_array.sh       '0-63%64'  1   4G    04:00:00  cpu;  j02=$REPLY
submit_stage 03  "afterok:$j02"       03_dedup.sh                 ''         1   16G   06:00:00  cpu;  j03=$REPLY
submit_stage 03b "afterok:$j03"       03b_partition.sh            ''         1   8G    12:00:00  cpu;  j03b=$REPLY
submit_stage 04  "afterok:$j03b"      04_conformers_250cpu.sbatch ''         "$STAGE04_CPUS" "$STAGE04_MEM" "$STAGE04_TIME" h200; j04=$REPLY
# afterany is deliberate: Stage 05 generates a missing-shard report even if
# Stage 04 exits nonzero. The finalizer fails closed if LMDB is incomplete.
submit_stage 05  "afterany:$j04"      05_finalize.sh              ''         1   8G    12:00:00  cpu;  j05=$REPLY

printf '\nAll REAL jobs submitted. IDs: 01=%s 02=%s 03=%s 03b=%s 04=%s 05=%s\n' "$j01" "$j02" "$j03" "$j03b" "$j04" "$j05"
printf 'Monitor: squeue -j %s,%s,%s,%s,%s,%s\n' "$j01" "$j02" "$j03" "$j03b" "$j04" "$j05"
printf 'Submission record: %s\n' "$RECORD"
printf 'Stage 04: %s logical CPUs, %s RDKit processes, %s RAM, %s, node %s\n' "$STAGE04_CPUS" "$STAGE04_WORKERS" "$STAGE04_MEM" "$H200_GRES" "${H200_NODE:-scheduler-selected}"
