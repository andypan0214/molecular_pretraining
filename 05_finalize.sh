#!/bin/bash
#SBATCH --partition=gpu
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=12:00:00
#SBATCH --job-name=lipid-05-final
#SBATCH --output=/project/yli4/ypan/lipid_library/logs/%x-%j.out
#SBATCH --error=/project/yli4/ypan/lipid_library/logs/%x-%j.err
# =============================================================================
# Stage 05 (CPU): fail-closed finalisation (review P0-1).
# Existing finalized production library: run HEART_STAGE05_AUDIT_ONLY=1 for a
# NON-DESTRUCTIVE 3D accounting audit; do not re-finalize the copied shards.
#   1. `lmdb_writer --finalize` with the SAME options as stage 04: recomputes the
#      expected shard layout from the enumeration + drop list, requires every
#      expected shard with matching configuration/input fingerprints and LMDB
#      hash, and reconciles counts. Only then is manifest.json written. On
#      failure it lists the missing shards and the array task ids to resubmit.
#   2. splits.json from whole shards (refuses smoke data, an empty valid split
#      or overlap). Validation shards: one drawn per stratum of the combination
#      order (v2 review P1; seed SPLIT_SEED, default 1), VALID_FRACTION of the
#      shards (default 0.002) or VALID_SHARDS shards; split_report.json gives the
#      validation fraction, positions and reagent-ID distribution per split.
#   3. record-level validation against the model dict.txt.
#
#   HEART_CONFIRM_LIPID=1 STORE_2D=<as stage 04> sbatch --export=ALL \
#       --dependency=afterany:<04 array id> scripts/lipid_library/05_finalize.sh
# LIPID_ARRAY_SIZE (default 1000) = the stage-04 stride, for the resubmit list.
# VALIDATE_ALL=1 checks every record (slow); the default samples 500 per shard.
# =============================================================================
set -eo pipefail
# Locate this Home checkout (sbatch may run a spooled copy); no legacy checkout fallback.
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ ! -f "$here/lipid_lib.sh" ]; then
    if [ -n "${HEART_REPO:-}" ]; then
        here="$HEART_REPO/model/pretrain/scripts/lipid_library"
    elif [ -n "${SLURM_JOB_ID:-}" ] && command -v scontrol >/dev/null 2>&1; then
        here="$(dirname "$(scontrol show job "$SLURM_JOB_ID" | sed -n 's/^ *Command=//p' | head -1 | cut -d' ' -f1)")"
    fi
fi
[ -f "$here/lipid_lib.sh" ] || { echo "ERROR: cannot locate scripts/lipid_library (set HEART_REPO)" >&2; exit 1; }
# Safe audit mode deliberately precedes lipid_init and all production cleanup.
# It uses the existing Project data and writes only separate audit reports.
if [ "${HEART_STAGE05_AUDIT_ONLY:-0}" = "1" ]; then
    repo="$(cd "$here/../../../.." && pwd)"
    export PYTHONPATH="$repo/model/pretrain${PYTHONPATH:+:$PYTHONPATH}"
    "${HEART_PYTHON:-python}" -m lipid_library.audit_existing_3d \
        "${LIPID_LMDB_DIR:-${LIPID_ROOT:-/project/yli4/ypan/lipid_library}/lmdb}" \
        --out-dir "${HEART_STAGE05_AUDIT_OUT:-/project/yli4/ypan/audits/ugi_3d_readiness}"
    exit $?
fi
# A finalized library must never be silently rewritten merely to resolve QC.
if [ -f "${LIPID_LMDB_DIR:-${LIPID_ROOT:-/project/yli4/ypan/lipid_library}/lmdb}/manifest.json" ]; then
    echo "REFUSED: Stage 05 artifacts already exist. Do NOT rerun finalize on the completed library." >&2
    echo "Use HEART_STAGE05_AUDIT_ONLY=1 bash $here/05_finalize.sh instead." >&2
    exit 2
fi
# shellcheck source=lipid_lib.sh
. "$here/lipid_lib.sh"
lipid_init "$here/05_finalize.sh"
lipid_writer_args
workers="${LIPID_STAGE05_WORKERS:-${SLURM_CPUS_PER_TASK:-1}}"
rm -f "$LIPID_LMDB/library_ready.json" "$LIPID_LMDB/library_integrity.json" "$LIPID_LMDB/library_verified.json" "$LIPID_LMDB/quality_report.json"
"$PY" -m lipid_library.lmdb_writer "$LIPID_ENUM" -o "$LIPID_LMDB" "${LIPID_WRITER_ARGS[@]}" \
    --finalize --array-size "${LIPID_ARRAY_SIZE:-${ARRAY_SIZE:-1000}}" --workers "$workers" \
    || die "finalize failed: see $LIPID_LMDB/finalize_report.json (missing shards / resubmit list)"
if [ -n "${VALID_SHARDS:-}" ]; then
    split_args=(--valid-shards "$VALID_SHARDS")
else
    split_args=(--valid-fraction "${VALID_FRACTION:-0.002}")
fi
split_args+=(--split-seed "${SPLIT_SEED:-1}" --split-method stratified-random)
ready_args=()
if [ -n "${LIMIT:-}" ]; then split_args+=(--allow-smoke); ready_args+=(--allow-smoke); fi
"$PY" -m lipid_library.splits "$LIPID_LMDB" "${split_args[@]}"
scope=(--sample "${VALIDATE_SAMPLE:-500}")
[ "${VALIDATE_ALL:-0}" = "1" ] && scope=(--all)
slots=10; [ "$STORE_2D" = "1" ] && slots=11
"$PY" -m lipid_library.validate_lmdb --manifest "$LIPID_LMDB/manifest.json" --dict "$LIPID_DICT" \
    --expect-slots "$slots" --max-atoms "${MAX_ATOMS:-256}" --only-polar 0 "${scope[@]}" \
    --audit-fallback --workers "$workers" \
    --json-out "$LIPID_LMDB/validation.json" || die "validation failed: see $LIPID_LMDB/validation.json"
"$PY" -c 'import json, sys
r = json.load(open(sys.argv[1]))
print("measured_sec_per_molecule = {} (CPU seconds per input molecule, one worker)".format(
    r.get("measured_sec_per_molecule")))' "$LIPID_LMDB/finalize_report.json"
# v2: production-quality criteria (config library.quality; docs/LIBRARY_QUALITY_CRITERIA.md).
# Always writes quality_report.json/.md; a production library failing a criterion stops here.
"$PY" -m lipid_library.quality "$LIPID_LMDB" --enum-dir "$LIPID_ENUM" --dedup-dir "$LIPID_DEDUP" \
    --workers "$workers" \
    || die "production-quality criteria not met: see $LIPID_LMDB/quality_report.md (no library_ready.json)"
# Receipt + per-shard integrity table (size, mtime, sampled digest); finalize above was the full sha256 pass.
"$PY" -m lipid_library.ready write "$LIPID_LMDB" "${ready_args[@]}" --workers "$workers" \
    || die "library_ready.json not written (see the problems above)"
log "ready: HEART_LIPID_SPLITS=$LIPID_LMDB/splits.json ($LIPID_LMDB/library_ready.json)"
