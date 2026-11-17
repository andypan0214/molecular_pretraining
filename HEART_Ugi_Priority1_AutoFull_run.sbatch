#!/bin/bash
#SBATCH --job-name=heart-ugi-P1-auto
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=32
#SBATCH --mem=128G
#SBATCH --time=2-00:00:00
#SBATCH --output=heart-ugi-P1-auto-%j.out
#SBATCH --error=heart-ugi-P1-auto-%j.err

# New runner for HEART_Ugi_Priority1_AutoFull_EN.ipynb only.
# Submit from /home/ypan/heart_liver/model_train with sbatch <this-file>.
set -euo pipefail
module load miniconda3/py311_24.1.2
# conda shell activation in batch context
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate /home/ypan/.conda/envs/heart_gpu
cd /home/ypan/heart_liver/model_train

export HEART_AUDIT_AUTORUN=1
export HEART_AUDIT_WORKERS=24
export HEART_AUDIT_BATCH_SHARDS=40
export PYTHONUNBUFFERED=1

python - <<'PY_CHECK'
import sys, rdkit, numpy, pandas, matplotlib, lmdb, joblib, nbconvert, nbformat, ipykernel
print('Python:',sys.executable,flush=True)
print('All required audit and notebook packages import successfully.',flush=True)
PY_CHECK

NOTEBOOK=HEART_Ugi_Priority1_AutoFull_EN.ipynb
OUTPUT=HEART_Ugi_Priority1_AutoFull_Executed.ipynb
test -f "$NOTEBOOK" || { echo "Notebook missing: $PWD/$NOTEBOOK" >&2; exit 2; }
python -m jupyter nbconvert --to notebook --execute "$NOTEBOOK" \
    --output "$OUTPUT" \
    --ExecutePreprocessor.timeout=-1

echo 'Notebook execution completed. Scientific gate is in ugi_priority1_interactive_evidence/07_priority1_evidence_decision.md'
