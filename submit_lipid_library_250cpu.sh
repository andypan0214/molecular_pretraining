#!/usr/bin/env bash
# Submit the existing stages once, in order: 01 -> 02 -> 03 -> 03b -> 04(250 CPUs) -> 05.
# SAFETY: dry-run by default; only --submit schedules the full production pipeline.
# This is a SUBMISSION SCRIPT, NOT an sbatch job: run from a CMRI login node.
set -Eeuo pipefail
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
ROOT="${LIPID_ROOT:-/home/ypan/heart_liver/model_train/lipid_library}"
MODE="${1:---dry-run}"
[[ "$MODE" == --dry-run || "$MODE" == --submit ]] || { echo 'Usage: bash submit_lipid_library_250cpu.sh [--dry-run|--submit]' >&2; exit 2; }
for file in 01_building_blocks.sh 02_enumerate_array.sh 03_dedup.sh 03b_partition.sh 04_conformers_250cpu.sbatch 05_finalize.sh; do
  [[ -r "$HERE/$file" ]] || { echo "Missing $HERE/$file" >&2; exit 2; }
done
[[ "${LIMIT:-}" == '' ]] || { echo 'Remove LIMIT (smoke-only setting) for production' >&2; exit 2; }
[[ "${LIPID_ARRAY_SIZE:-1000}" == 1000 ]] || { echo 'Use LIPID_ARRAY_SIZE=1000 to preserve existing shard mapping' >&2; exit 2; }
if [[ "$MODE" == --submit ]]; then
  command -v sbatch >/dev/null || { echo 'sbatch not found' >&2; exit 2; }
  [[ -r "${LIPID_INPUT:-$ROOT/input/LUMI_virtual_library_training_lipidLike.xlsx}" ]] || { echo 'Missing LUMI Excel input file' >&2; exit 2; }
  mkdir -p "$ROOT/logs"
  # Verify both resource classes BEFORE submitting any dependent jobs.
  # A CPU-only request may not be allowed on the gpu partition.
  sbatch --test-only --partition=gpu --nodes=1 --ntasks=1 \
    --cpus-per-task=1 --mem=4G --time=00:02:00 --wrap=true >/dev/null \
    || { echo 'CPU-only jobs are not accepted on gpu partition; do not submit.' >&2; exit 2; }
  sbatch --test-only --partition=gpu --nodes=1 --ntasks=1 \
    --cpus-per-task=250 --mem=500G --gres=gpu:1 --time=00:02:00 \
    --wrap=true >/dev/null \
    || { echo '250 CPUs / 500G / H200 allocation not accepted; do not submit.' >&2; exit 2; }
fi
# Small stages deliberately request CPU-only resources on partition gpu. The site
# must permit CPU-only jobs there; verify with `sbatch --test-only` before --submit.
# Stage 04 explicitly requests the tested H200 GPU and 250CPU/500G allocation.
ex="ALL,HEART_CONFIRM_LIPID=1,STORE_2D=0,LIPID_ROOT=$ROOT,LIPID_ARRAY_SIZE=1000,LIPID_WORKERS=${LIPID_WORKERS:-250},LIPID_ENUM_ARRAY_SIZE=64"
submit() {
  local label="$1" dep="$2" file="$3" array="$4" cpu="$5" mem="$6" time="$7"
  local -a cmd=(sbatch --parsable --partition=gpu --export="$ex")
  [[ -z "$dep" ]] || cmd+=("--dependency=afterok:$dep")
  [[ -z "$array" ]] || cmd+=("--array=$array")
  if [[ "$label" != 04 ]]; then
    cmd+=(--nodes=1 --ntasks=1 "--cpus-per-task=$cpu" "--mem=$mem" "--time=$time")
  fi
  if [[ -z "$array" ]]; then
    cmd+=("--output=$ROOT/logs/%x-%j.out" "--error=$ROOT/logs/%x-%j.err")
  else
    cmd+=("--output=$ROOT/logs/%x-%A_%a.out" "--error=$ROOT/logs/%x-%A_%a.err")
  fi
  cmd+=("$HERE/$file")
  if [[ "$MODE" == --dry-run ]]; then
    printf '[DRY RUN] %-4s ' "$label"; printf '%q ' "${cmd[@]}"; echo
    REPLY="PREVIEW_$label"
  else
    REPLY="$("${cmd[@]}")"
    REPLY="${REPLY%%;*}"
    [[ "$REPLY" =~ ^[0-9]+$ ]] || { echo "Unexpected sbatch response $REPLY" >&2; exit 2; }
    echo "Submitted stage $label: $REPLY" >&2
  fi
}
submit 01 '' 01_building_blocks.sh '' 1 4G 00:30:00; j01=$REPLY
submit 02 "$j01" 02_enumerate_array.sh 0-63%64 1 4G 04:00:00; j02=$REPLY
submit 03 "$j02" 03_dedup.sh '' 1 16G 06:00:00; j03=$REPLY
submit 03b "$j03" 03b_partition.sh '' 1 8G 12:00:00; j03b=$REPLY
submit 04 "$j03b" 04_conformers_250cpu.sbatch '' 250 500G 2-00:00:00; j04=$REPLY
# Stage 05 afterany: still produce a missing-shard report if stage04 fails.
# SLURM afterany cannot use the afterok helper above, so submit explicitly.
cmd=(sbatch --parsable --partition=gpu --nodes=1 --ntasks=1 --cpus-per-task=1 --mem=8G --time=12:00:00
     "--dependency=afterany:$j04" "--export=$ex" "--output=$ROOT/logs/%x-%j.out" "--error=$ROOT/logs/%x-%j.err"
     "$HERE/05_finalize.sh")
if [[ "$MODE" == --dry-run ]]; then
  printf '[DRY RUN] 05   '; printf '%q ' "${cmd[@]}"; echo
else
  j05="$("${cmd[@]}")"; echo "Submitted stage 05: ${j05%%;*}" >&2
fi
printf '\n%s\n' 'Note: gpu partition must allow CPU-only jobs in stages 01/02/03/03b/05.'
if [[ "$MODE" == --dry-run ]]; then
  echo 'DRY RUN only; no jobs submitted. Do not use --submit before CMRI benchmarks and review.'
else
  echo 'All six stages submitted; SLURM dependencies execute them in order.'
fi
