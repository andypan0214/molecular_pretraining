#!/usr/bin/env python3
"""Read-only HEART v2 Project storage migration audit.

Default: full SHA-256 comparisons with available original data copies. This may
read many hundreds of GB and should run on an HPC compute node if feasible.
No external Python dependencies; never deletes, rewrites, copies or trains.

Usage:
  python check_project_data_integrity.py
  python check_project_data_integrity.py --quick  # inventory only, NOT deletion proof
  python check_project_data_integrity.py --source-lipid /path/to/original/lipid_library
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_PROJECT = Path('/project/yli4/ypan')
DEFAULT_REPO = Path('/home/ypan/heart_liver/model_train/heart-molecular-pretraining-v2')
EXPECTED_SHARDS = 3049
EXPECTED_PRODUCTS = 15241216
EXPECTED_STORED = 15182715
ESSENTIAL_LIBRARY_DIRS = ('input', 'bb', 'enum', 'dedup', 'lmdb')


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda: f.read(16 * 1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def json_file(p: Path):
    with p.open('r', encoding='utf-8') as f:
        return json.load(f)


def enumerate_files(base: Path, subdirs: tuple[str, ...]) -> dict[str, Path]:
    result = {}
    for d in subdirs:
        root = base / d
        if not root.is_dir():
            continue
        for path in root.rglob('*'):
            if path.is_file() and not path.is_symlink():
                result[path.relative_to(base).as_posix()] = path
    return result


class Audit:
    def __init__(self):
        self.checks = []
        self.failures = []
        self.warnings = []

    def emit(self, state: str, name: str, info: str):
        line = f'[{state}] {name}: {info}'
        print(line, flush=True)
        self.checks.append({'status': state, 'check': name, 'detail': info})
        if state == 'FAIL':
            self.failures.append(line)
        elif state == 'WARN':
            self.warnings.append(line)

    def ok(self, name, info): self.emit('PASS', name, info)
    def fail(self, name, info): self.emit('FAIL', name, info)
    def warn(self, name, info): self.emit('WARN', name, info)


def verify_file(a: Audit, name: str, path: Path, must_be_nonempty=True) -> bool:
    if not path.is_file():
        a.fail(name, f'missing: {path}')
        return False
    if must_be_nonempty and path.stat().st_size <= 0:
        a.fail(name, f'empty: {path}')
        return False
    a.ok(name, str(path))
    return True


def source_candidates(project: Path, explicit: Path | None, kind: str):
    if explicit is not None:
        return [explicit]
    if kind == 'lipid':
        return [
            project / 'model_train/lipid_library',
            Path('/scratch/ypan/heart_liver/model_train/lipid_library'),
            Path('/home/ypan/heart_liver/model_train/lipid_library'),
        ]
    if kind == 'reference':
        return [
            project / 'model_train/UniMolReference/ligand_data/ligands',
            Path('/scratch/ypan/heart_liver/model_train/UniMolReference/ligand_data/ligands'),
            Path('/home/ypan/heart_liver/model_train/UniMolReference/ligand_data/ligands'),
        ]
    return [
        project / 'model_train/runs/h200/full/heart-h200-b448-v1/checkpoint_best.pt',
        Path('/home/ypan/heart_liver/model_train/heart-molecular-pretraining/runs/h200/full/heart-h200-b448-v1/checkpoint_best.pt'),
        Path('/scratch/ypan/heart_liver/model_train/heart-molecular-pretraining-v2/runs/h200/full/heart-h200-b448-v1/checkpoint_best.pt'),
    ]


def candidate_exists(x: Path, dest: Path):
    try:
        return x.exists() and x.resolve() != dest.resolve()
    except OSError:
        return False


def compare_one(pair):
    rel, src, dst = pair
    try:
        s1, s2 = src.stat(), dst.stat()
        if s1.st_size != s2.st_size:
            return rel, f'size mismatch ({s1.st_size} != {s2.st_size})'
        if sha256_file(src) != sha256_file(dst):
            return rel, 'SHA-256 mismatch'
        # Detect files changed mid-check; copy may still be running.
        s1b, s2b = src.stat(), dst.stat()
        if (s1.st_size, s1.st_mtime_ns) != (s1b.st_size, s1b.st_mtime_ns) or \
           (s2.st_size, s2.st_mtime_ns) != (s2b.st_size, s2b.st_mtime_ns):
            return rel, 'file changed during audit (copy/write may still be running)'
        return rel, None
    except (OSError, PermissionError) as exc:
        return rel, f'cannot read: {exc}'


def compare_sets(a: Audit, name: str, src: Path, dst: Path, subs: tuple[str, ...], full: bool, workers: int) -> bool:
    print(f'\n--- {name} from {src} ---', flush=True)
    src_files = enumerate_files(src, subs)
    dst_files = enumerate_files(dst, subs)
    if not src_files:
        a.warn(name, f'source contains no recognized files; cannot attest {src}')
        return False
    absent = sorted(set(src_files) - set(dst_files))
    if absent:
        a.fail(name, f'{len(absent)} source files missing in Project: {absent[:6]}')
        return False
    pairs = [(k, src_files[k], dst_files[k]) for k in sorted(src_files)]
    if not full:
        a.warn(name, f'QUICK ONLY: {len(pairs)} filenames matched; no byte-level verification')
        return False
    print(f'Computing SHA-256 for {len(pairs):,} file pairs (read-only; can be slow on large LMDBs)...', flush=True)
    problems = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(compare_one, pair) for pair in pairs]
        for i, future in enumerate(as_completed(futures), 1):
            rel, error = future.result()
            if error:
                problems.append((rel, error))
            if i % 250 == 0 or i == len(pairs):
                print(f'  hashed {i:,}/{len(pairs):,} pairs; mismatches {len(problems)}', flush=True)
    if problems:
        a.fail(name, f'{len(problems)} checksum/read mismatches; first: {problems[:5]}')
        return False
    a.ok(name, f'{len(pairs):,} source files match Project byte-for-byte (SHA-256)')
    extra = set(dst_files) - set(src_files)
    if extra:
        a.warn(name + ' additional Project files', f'{len(extra)} destination-only files (not a copy failure); e.g. {sorted(extra)[:5]}')
    return True


def compare_few(a: Audit, name: str, src: Path | None, dst: Path, full: bool) -> bool:
    if src is None:
        a.warn(name, f'original source not found; cannot attest original bytes of {dst}')
        return False
    if not full:
        a.warn(name, 'QUICK ONLY: full file SHA-256 not run')
        return False
    rel, problem = compare_one((dst.name, src, dst))
    if problem:
        a.fail(name, f'{src} -> {dst}: {problem}')
        return False
    a.ok(name, f'SHA-256 matched {src}')
    return True


def sha_ref_check(a, splits: dict, manifest_path: Path):
    # Only compare clearly-named, top-level expected hashes. Avoid guessing schemas.
    candidates = ['manifest_sha256', 'manifest_hash', 'manifest_digest']
    found = [(k, splits[k]) for k in candidates if k in splits]
    if not found:
        a.warn('Splits / manifest linkage', 'no recognized top-level manifest hash; schema-specific cross-check pending')
        return
    digest = sha256_file(manifest_path)
    for key, value in found:
        if not isinstance(value, str) or value.lower().removeprefix('sha256:') != digest:
            a.fail('Splits / manifest linkage', f'{key} does not match manifest file SHA-256')
        else:
            a.ok('Splits / manifest linkage', f'{key} verified')


def lmdb_probe(a: Audit, path: Path, name: str, required: bool = False):
    try:
        import lmdb
    except ImportError:
        a.warn(name, 'python-lmdb not installed; bytes/checksum will be checked but LMDB open test skipped')
        return
    try:
        env = lmdb.open(str(path), subdir=path.is_dir(), readonly=True, lock=False, readahead=False, max_readers=8)
        with env.begin(write=False) as txn:
            count = int(txn.stat()['entries'])
            cursor = txn.cursor()
            has_first = bool(cursor.first())
        env.close()
        if count <= 0 or not has_first:
            a.fail(name, f'LMDB appears empty: {path}')
        else:
            a.ok(name, f'opened read-only; {count:,} records')
    except Exception as exc:
        a.fail(name, f'LMDB cannot open read-only: {type(exc).__name__}: {exc}')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project-root', type=Path, default=DEFAULT_PROJECT)
    p.add_argument('--repo', type=Path, default=DEFAULT_REPO)
    p.add_argument('--source-lipid', type=Path, default=None)
    p.add_argument('--source-reference', type=Path, default=None)
    p.add_argument('--source-checkpoint', type=Path, default=None)
    p.add_argument('--expected-shards', type=int, default=EXPECTED_SHARDS)
    p.add_argument('--workers', type=int, default=2)
    p.add_argument('--quick', action='store_true', help='inventory only; never sufficient to authorize deleting original')
    p.add_argument('--report', type=Path, default=Path.cwd() / 'project_data_integrity_report.json')
    args = p.parse_args()
    if not 1 <= args.workers <= 8:
        p.error('--workers must be between 1 and 8')
    project = args.project_root
    repo = args.repo
    lib = project / 'lipid_library'
    lmdb_dir = lib / 'lmdb'
    reference = project / 'UniMolReference/ligand_data/ligands'
    checkpoint = project / 'runs/h200/full/heart-h200-b448-v1/checkpoint_best.pt'
    a = Audit()
    started = time.time()
    print('=== HEART v2 PROJECT DATA INTEGRITY AUDIT (READ-ONLY) ===')
    print(f'Project: {project}\nHome code: {repo}\nDeep SHA-256: {not args.quick}')
    # Code and canonical Project dirs; never require Project code checkout.
    verify_file(a, 'Home v2 CLI', repo / 'bin/heart')
    for name, root in [('Project lipid library',lib),('Project LMDB',lmdb_dir),('Project reference',reference),('Project checkpoint runs',project/'runs')]:
        (a.ok if root.is_dir() else a.fail)(name, str(root))
    for folder in ESSENTIAL_LIBRARY_DIRS:
        if (lib / folder).is_dir():
            a.ok('Library folder '+folder, str(lib/folder))
        else:
            a.fail('Library folder '+folder, f'missing {lib/folder}')
    for rel in ['dedup/drop_combo_indexes.csv.gz','enum/enumeration_complete.json',
                'lmdb/lmdb_writer_config.json','lmdb/shard_inputs/partition_config.json',
                'lmdb/shard_inputs/partition_index.json',
                'lmdb/manifest.json', 'lmdb/splits.json', 'lmdb/quality_report.json',
                'lmdb/finalize_report.json','lmdb/validation.json']:
        verify_file(a,'Library '+rel,lib/rel)
    # SHARD pairing across all 3049, independent of filenames of extra files.
    receipts = sorted(lmdb_dir.glob('shard-*/shard.json'))
    if len(receipts) == args.expected_shards:
        a.ok('Stage 04 receipts', f'{len(receipts)} / {args.expected_shards}')
    else:
        a.fail('Stage 04 receipts', f'{len(receipts)} / {args.expected_shards}')
    bad_pairs = []
    for receipt in receipts:
        x = receipt.parent / 'train.lmdb'
        if not x.is_file() or x.stat().st_size <= 0:
            bad_pairs.append(str(x))
    if not bad_pairs and len(receipts) == args.expected_shards:
        a.ok('Stage 04 LMDB shard files', f'nonempty train.lmdb present for all {len(receipts)} receipts')
    else:
        a.fail('Stage 04 LMDB shard files', f'{len(bad_pairs)} missing/empty: {bad_pairs[:5]}')
    # Stage 05 JSON self-consistency and intentional FAILED quality gate.
    manifest, splits, qc = (None, None, None)
    for key, file in [('manifest',lmdb_dir/'manifest.json'),('splits',lmdb_dir/'splits.json'),('quality',lmdb_dir/'quality_report.json')]:
        if file.is_file():
            try:
                v = json_file(file)
                if not isinstance(v, dict): raise ValueError('expected JSON object')
                if key == 'manifest': manifest=v
                elif key == 'splits': splits=v
                else: qc=v
                a.ok(key+' JSON parsing', f'{len(v)} top-level keys')
            except Exception as exc:
                a.fail(key+' JSON parsing', str(exc))
    if splits is not None and manifest is not None:
        sha_ref_check(a,splits,lmdb_dir/'manifest.json')
    if qc is not None:
        dedup = qc.get('dedup',{})
        if isinstance(dedup,dict):
            n = dedup.get('n_unique_products')
            if isinstance(n,int) and args.expected_shards == EXPECTED_SHARDS:
                (a.ok if n == EXPECTED_PRODUCTS else a.fail)('Ugi unique products',f'{n:,} (expected {EXPECTED_PRODUCTS:,})')
        stage4 = qc.get('stage04',{})
        n_stored = stage4.get('accepted_records') if isinstance(stage4,dict) else None
        if n_stored is not None and isinstance(n_stored,int):
            (a.ok if n_stored == EXPECTED_STORED else a.fail)('Stored records',f'{n_stored:,} (expected {EXPECTED_STORED:,})')
        if qc.get('passed') is False:
            a.warn('Scientific Stage 05 QC', 'original QC is FAILED (2D fallback thresholds); copy verification does NOT fix readiness')
        elif qc.get('passed') is True:
            a.warn('Scientific Stage 05 QC', 'original QC now reports PASS; inspect provenance before trusting this change')
        else:
            a.fail('Scientific Stage 05 QC', 'missing/invalid QC passed field')
    # Reference and model checkpoint.
    for f in ('train.lmdb','valid.lmdb','dict.txt'):
        verify_file(a,'UniMolReference '+f,reference/f)
    verify_file(a,'General H200 checkpoint',checkpoint)
    # Lightweight actual LMDB read; cannot prove copy integrity, but detects broken file headers.
    if reference.is_dir():
        for f in ('train.lmdb','valid.lmdb'):
            if (reference/f).is_file():lmdb_probe(a,reference/f,'Reference '+f+' read')
    if receipts:
        lmdb_probe(a,receipts[0].parent/'train.lmdb','Lipid first shard read')
        lmdb_probe(a,receipts[-1].parent/'train.lmdb','Lipid last shard read')
    # Candidate sources: only compare if truly independent, not same directory or symlink.
    lip_sources = [x for x in source_candidates(project,args.source_lipid,'lipid') if candidate_exists(x,lib)]
    ref_sources = [x for x in source_candidates(project,args.source_reference,'reference') if candidate_exists(x,reference)]
    ckpt_sources = [x for x in source_candidates(project,args.source_checkpoint,'checkpoint') if candidate_exists(x,checkpoint)]
    lip_attest = []
    for src in lip_sources:
        if src.is_dir() and (src/'lmdb').is_dir() and len(list((src/'lmdb').glob('shard-*/shard.json'))) == args.expected_shards:
            ok = compare_sets(a,'Lipid full-tree source comparison',src,lib,('',),not args.quick,args.workers)
            lip_attest.append({'source':str(src),'matched':ok})
        else:
            a.warn('Lipid source comparison',f'candidate not a full {args.expected_shards}-shard original, skipped: {src}')
    if not lip_attest:
        a.warn('Lipid source comparison','no full original library copy found; cannot certify all destination bytes match the original')
    ref_attest = []
    for src in ref_sources:
        if not src.is_dir(): continue
        outcomes = [compare_few(a,'Reference '+f+' source comparison',src/f if (src/f).is_file() else None,reference/f,not args.quick)
                    for f in ('train.lmdb','valid.lmdb','dict.txt') if (reference/f).is_file()]
        ref_attest.append({'source':str(src),'matched':len(outcomes)==3 and all(outcomes)})
    if not ref_attest:
        a.warn('Reference source comparison','no independent reference source available for SHA-256 comparison')
    ckpt_attest = []
    for src in ckpt_sources:
        if src.is_file() and checkpoint.is_file():
            ckpt_attest.append({'source':str(src),'matched':compare_few(a,'Checkpoint source comparison',src,checkpoint,not args.quick)})
    if not ckpt_attest:
        a.warn('Checkpoint source comparison','no independent original checkpoint available for SHA-256 comparison')
    lib_ready_to_retire = bool(lip_attest) and all(x['matched'] for x in lip_attest) and not args.quick
    ref_ready_to_retire = bool(ref_attest) and all(x['matched'] for x in ref_attest) and not args.quick
    ckpt_ready_to_retire = bool(ckpt_attest) and all(x['matched'] for x in ckpt_attest) and not args.quick
    no_fail = not a.failures
    print('\n========== FINAL RESULT ==========')
    print('Required Project data structurally valid:', 'YES' if no_fail else 'NO')
    print('Lipid source byte-level attestation:', 'PASS' if lib_ready_to_retire else 'NOT VERIFIED')
    print('Reference source byte-level attestation:', 'PASS' if ref_ready_to_retire else 'NOT VERIFIED')
    print('Checkpoint source byte-level attestation:', 'PASS' if ckpt_ready_to_retire else 'NOT VERIFIED')
    print('Stage 05 scientific ready:', 'NO - QC requires separate resolution' if qc and qc.get('passed') is False else 'UNVERIFIED')
    print('Required-data source integrity:', 'PASS (review individual old paths before deletion)' if no_fail and lib_ready_to_retire and ref_ready_to_retire and ckpt_ready_to_retire else 'NOT FULLY VERIFIED')
    print('No deletion performed or authorized by this audit. Never delete the Home v2 source code repository.')
    report = {'timestamp_utc':datetime.now(timezone.utc).isoformat(),
              'project':str(project),'repo':str(repo),'quick':args.quick,
              'expected_shards':args.expected_shards,
              'structural_passed':no_fail,'lipid_attestations':lip_attest,
              'reference_attestations':ref_attest,'checkpoint_attestations':ckpt_attest,
              'required_data_integrity_attested':bool(no_fail and lib_ready_to_retire and ref_ready_to_retire and ckpt_ready_to_retire),
              'deletion_authorized':False,
              'deletion_note':'No deletion is authorized automatically. Review exact source paths; library full-tree, reference trio and checkpoint only are compared.',
              'scientific_qc_passed':None if qc is None else qc.get('passed'),
              'errors':a.failures,'warnings':a.warnings,'checks':a.checks,
              'elapsed_seconds':round(time.time()-started,1)}
    try:
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
        print('Report:',args.report)
    except Exception as exc:
        print('Cannot save report (source data unmodified):',exc)
    return 0 if no_fail else 2


if __name__=='__main__':
    sys.exit(main())
