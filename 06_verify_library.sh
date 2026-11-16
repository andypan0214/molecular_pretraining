#!/bin/bash
#SBATCH --partition=gpu
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=32G
#SBATCH --time=12:00:00
#SBATCH --job-name=lipid-06-verify
#SBATCH --output=/project/yli4/ypan/lipid_library/logs/%x-%j.out
#SBATCH --error=/project/yli4/ypan/lipid_library/logs/%x-%j.err
# =============================================================================
# Optional FULL re-verification of an ALREADY QC-READY lipid library: the sha256 of every
# shard LMDB (~0.4 TB, 16 threads) must equal manifest.json. Read-only on the shards; on success it
# refreshes library_integrity.json (quick-check table) and writes library_verified.json, whose date
# satisfies continual.full_verify_max_age_days. Submit with:
#   bin/heart library --verify-full --dry-run | --submit
# Only for a library that has passed original Stage 05 QC and has library_ready.json.
# This does not repair the existing failed QC or make a filtered view ready.
# Stage 05 already performs this full hash once; run this job when the library is older than the
# allowed age, was copied/moved, or a quick check reported a changed shard.
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
# shellcheck source=lipid_lib.sh
. "$here/lipid_lib.sh"
lipid_init "$here/06_verify_library.sh"
# Explicit fail-fast before expensive full hashing. ready.verify also enforces
# this requirement, but printing it now avoids unnecessary HPC resource use.
if [ ! -f "$LIPID_LMDB/library_ready.json" ]; then
    echo "NOT READY: $LIPID_LMDB/library_ready.json is absent (original Stage 05 QC failed)." >&2
    echo "This verification cannot override QC. Run the read-only Stage 05 audit instead." >&2
    exit 2
fi
ready_args=()
[ -n "${LIMIT:-}" ] && ready_args+=(--allow-smoke)
"$PY" -m lipid_library.ready verify "$LIPID_LMDB" --full --workers "${SLURM_CPUS_PER_TASK:-16}" "${ready_args[@]}" \
    || die "FULL verification failed: see $LIPID_LMDB/library_verified.json"
log "full verification passed: $LIPID_LMDB/library_verified.json"
