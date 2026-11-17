#!/bin/bash
#SBATCH --partition=gpu
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=12:00:00
#SBATCH --job-name=ugi-3d-view
#SBATCH --output=/project/yli4/ypan/lipid_library/logs/%x-%j.out
#SBATCH --error=/project/yli4/ypan/lipid_library/logs/%x-%j.err
# Separate read-only Stage 05 *sidecar index preparation* for finalized library.
# Does not invoke the original 05_finalize.sh, alter QC or submit Stage 06.
set -euo pipefail
REPO=/home/ypan/heart_liver/model_train/heart-molecular-pretraining
SRC=/project/yli4/ypan/lipid_library/lmdb
OUT=/project/yli4/ypan/audits/ugi_3d_final_view
export PYTHONPATH="$REPO/model/pretrain${PYTHONPATH:+:$PYTHONPATH}"
# Use the existing interpreter/conda environment from Home. Do not install anything.
PY=/home/ypan/.conda/envs/heart_gpu/bin/python
"$PY" -m lipid_library.prepare_3d_view \
    --lmdb-dir "$SRC" \
    --out-dir "$OUT" \
    --lmdb-samples 4
