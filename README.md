# Molecular Pretraining — CPU / Jupyter Tests

CPU-first molecular data and model pipeline validation. This repository contains example test code, not pretrained weights or research data. Test notebook: `notebooks/Molecular_Pretraining_CPU_Validation.ipynb`.

## HPC JupyterLab: download without Git

In a fresh Jupyter cell run:

```python
import io, zipfile, urllib.request
from pathlib import Path
repo = "andypan0214/molecular_pretraining"
out = Path.cwd() / "molecular_pretraining_download_v1"
if out.exists():
    raise FileExistsError(f"Choose a new folder: {out}")
url = f"https://api.github.com/repos/{repo}/zipball/main"
req = urllib.request.Request(url, headers={"User-Agent": "HPC-Jupyter"})
with urllib.request.urlopen(req, timeout=120) as response:
    content = response.read()
with zipfile.ZipFile(io.BytesIO(content)) as archive:
    out.mkdir(parents=True)
    archive.extractall(out)
for p in out.iterdir():
    print("Open notebook:", p / "notebooks/Molecular_Pretraining_CPU_Validation.ipynb")
```

To update, use a NEW directory name (e.g. `molecular_pretraining_download_v2`) so existing notebooks/results are not overwritten. If Git is available: `git clone https://github.com/andypan0214/molecular_pretraining.git`.

## Notebook tests

Environment and dependencies → RDKit SMILES validation → 3D conformers → LMDB generation and round-trip → download public Uni-Mol/LUMI/Uni-Core source ZIPs → diagnose import compatibility → optional CPU model smoke test. No GPU partition or Git binary is required for initial data tests. Code is **not** a verified full training reproduction.

## Security

Repository is **public**. Only upload code approved for public release. Never commit institutional datasets, credentials, lab-private results, HPC logs, or checkpoints. Check institutional rules before transferring code.
