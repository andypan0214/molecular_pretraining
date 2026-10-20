"""Download a PUBLIC GitHub repository snapshot without requiring git.
Run from a Jupyter cell with %run scripts/update_from_github.py USER/REPO.
Uses the GitHub public REST API. Private repos need an approved authenticated workflow.
"""
import argparse
import io
import json
import re
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path


def download(repo, branch, destination):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise ValueError("Repository must be USER/REPO")
    if not re.fullmatch(r"[A-Za-z0-9_./-]+", branch) or '..' in branch:
        raise ValueError("Invalid branch")
    destination = Path(destination).expanduser().resolve()
    if destination.exists():
        raise FileExistsError(f"Refusing to overwrite {destination}. Choose a new --dest.")
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/zipball/{branch}",
        headers={"User-Agent": "Molecular-Pretraining-Updater", "Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(req, timeout=120) as response:
        data = response.read()
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        members = [i for i in z.infolist() if not i.is_dir()]
        roots = {i.filename.split('/')[0] for i in members}
        if len(roots) != 1:
            raise ValueError("Unexpected GitHub archive layout")
        root = roots.pop()
        with tempfile.TemporaryDirectory(dir=destination.parent) as temp:
            temp_path = Path(temp)
            for member in members:
                parts = Path(member.filename).parts
                rel = Path(*parts[1:])
                if not rel.parts or '..' in rel.parts:
                    raise ValueError(f"Unsafe archive path: {member.filename}")
                target = (temp_path / rel).resolve()
                if not target.is_relative_to(temp_path.resolve()):
                    raise ValueError(f"Unsafe archive path: {member.filename}")
                target.parent.mkdir(parents=True, exist_ok=True)
                if (member.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError("Symlinks are not accepted")
                with z.open(member) as src, open(target, 'wb') as out:
                    shutil.copyfileobj(src, out)
            temp_path.rename(destination)
    print("Downloaded", repo, "branch", branch, "to", destination)
    print("Open notebooks/LUMI_Jupyter_CPU_GitHubReady_v2.ipynb in JupyterLab")

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('repo', help='Public USER/REPO')
    p.add_argument('--branch', default='main')
    p.add_argument('--dest', default='molecular-pretraining-new')
    args = p.parse_args()
    download(args.repo, args.branch, args.dest)
