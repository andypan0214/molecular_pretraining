#!/bin/bash
#SBATCH --job-name=heart-ugi-P1-cpu100
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=100
#SBATCH --mem=256G
#SBATCH --time=2-00:00:00
#SBATCH --output=heart-ugi-P1-cpu100-%j.out
#SBATCH --error=heart-ugi-P1-cpu100-%j.err

set -euo pipefail

# Run using the same activated Python/Conda environment as your working HEART Jupyter kernel.
# If that environment is not your login-shell default, activate it here before the checks.
NOTEBOOK_DIR="${HEART_AUDIT_HOME:-/home/ypan/heart_liver/model_train}"
if [[ ! -d "$NOTEBOOK_DIR" ]]; then echo "ERROR: notebook directory does not exist: $NOTEBOOK_DIR" >&2; exit 2; fi
cd "$NOTEBOOK_DIR"
export HEART_AUDIT_WORKERS="${HEART_AUDIT_WORKERS:-64}"
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export MKL_NUM_THREADS=1
export HEART_AUDIT_OUT="${HEART_AUDIT_OUT:-$NOTEBOOK_DIR/ugi_priority1_evidence}"
mkdir -p "$HEART_AUDIT_OUT"
echo "Running notebook: HEART_Ugi_Priority1_model_train_Parallel100CPU.ipynb"
echo "Host: $(hostname) | Slurm job: ${SLURM_JOB_ID:-unknown}"
echo "Notebook folder: $NOTEBOOK_DIR"
echo "Results folder: $HEART_AUDIT_OUT"
echo "Python: $(command -v python)"
echo "Audit parallel workers: $HEART_AUDIT_WORKERS"
echo "CPU affinity: $(taskset -pc $$ 2>/dev/null || true)"
python - <<'CHECK'
import rdkit, numpy, pandas, matplotlib, lmdb, nbconvert, ipykernel, joblib
from packaging.version import Version
assert Version(joblib.__version__) >= Version("1.3"), f"Need joblib >=1.3; found {joblib.__version__}"
print('Preflight imports OK: RDKit, NumPy, pandas, matplotlib, lmdb, nbconvert, ipykernel, joblib>=1.3')
CHECK

# Execute all cells on the compute node. Executed notebook appears in the model_train folder only after completion.
# Data-quality reports/figures are written incrementally by the notebook itself.
python -m jupyter nbconvert \
    --to notebook --execute HEART_Ugi_Priority1_model_train_Parallel100CPU.ipynb \
    --output HEART_Ugi_Priority1_Executed.ipynb \
    --ExecutePreprocessor.timeout=-1 \
    --ExecutePreprocessor.allow_errors=False

printf '\nCOMPLETED. Review: %s/07_priority1_evidence_decision.md\n' "$HEART_AUDIT_OUT"
