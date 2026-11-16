#!/usr/bin/env python3
"""Prepare a NON-DESTRUCTIVE Ugi-4CR 3D slot index from completed Stage-04 LMDB shards.

The original LMDBs and finalized Stage-05 reports stay untouched. Every stored molecule
with n_3d_success>=1 is retained, and the *first* n_3d_success coordinate slots are
identified as valid writer-generated 3D slots. No 3D coordinates are regenerated.

This generates a verified DATA INDEX ONLY. It deliberately does NOT write the original
library_ready.json and does NOT authorize production continual training. The continual
sampler must later be adapted to consult these sidecar counts and independently tested.

Usage (from repository root):
  PYTHONPATH=model/pretrain python -m lipid_library.prepare_3d_view \
    --lmdb-dir /project/yli4/ypan/lipid_library/lmdb \
    --out-dir /project/yli4/ypan/audits/ugi_3d_final_view
"""
import argparse
import csv
import gzip
import hashlib
import json
import os
import pickle
import shutil
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

N_SLOTS = 10


def load_json(p):
    with open(p, encoding='utf-8') as f:
        return json.load(f)


def sha256(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for block in iter(lambda: f.read(4 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def rel_path(rel):
    p = Path(rel)
    if p.is_absolute() or '..' in p.parts or not p.parts:
        raise ValueError('Unsafe relative path: {}'.format(rel))
    return p


def check_sources(src):
    names = ['manifest.json', 'splits.json', 'quality_report.json',
             'validation.json', 'finalize_report.json']
    for name in names:
        if not (src / name).is_file():
            raise ValueError('Missing source: ' + str(src / name))
    manifest, splits, qc, validation, finalize = [load_json(src / n) for n in names]
    mh = sha256(src / 'manifest.json')
    if manifest.get('complete') is not True or manifest.get('smoke'):
        raise ValueError('Manifest incomplete or smoke')
    if finalize.get('complete') is not True or finalize.get('config_fingerprint') != manifest.get('config_fingerprint'):
        raise ValueError('Finalize incomplete / fingerprint mismatch')
    if splits.get('complete') is not True or splits.get('smoke') or splits.get('manifest_sha256') != mh:
        raise ValueError('Splits incomplete, smoke or wrong manifest')
    if qc.get('manifest_sha256') != mh:
        raise ValueError('Original QC does not belong to manifest')
    if validation.get('n_problems') != 0 or validation.get('passed') is False:
        raise ValueError('Original validation has problems')
    shards = manifest.get('shards', [])
    if not shards or len(shards) != manifest.get('n_shards'):
        raise ValueError('Manifest shard count invalid')
    entries = {str(rel_path(s['lmdb'])) for s in shards}
    train, valid = [set(map(lambda x: str(rel_path(x)), splits[sn])) for sn in ('train','valid')]
    if train & valid or train | valid != entries or not train or not valid:
        raise ValueError('Train/valid shards overlap, are empty, or do not cover manifest')
    if len(entries) != len(shards):
        raise ValueError('Duplicate manifest shard paths')
    if set(s.get('dir') for s in shards) != {str(rel_path(s['lmdb']).parent) for s in shards}:
        raise ValueError('Shard directory and LMDB paths disagree')
    # Original validation stores absolute LMDB paths; manifest uses relative paths.
    checked = {'/'.join(Path(row['lmdb']).parts[-2:]) for row in validation.get('results', [])}
    if not entries.issubset(checked):
        raise ValueError('Original validation did not cover all manifest shards')
    return manifest, splits, qc, mh


def read_index_csv(path, n_records, n_slots=N_SLOTS):
    """Stream authoritative writer rows; enforce key-to-LMDB direct positional mapping."""
    counts = bytearray()
    first_2d = None
    hist = Counter()
    with gzip.open(path, 'rt', encoding='utf-8', newline='') as f:
        reader = csv.DictReader(f)
        required = {'key', 'n_coordinate_slots', 'n_3d_success', 'n_2d_filled'}
        if not required.issubset(reader.fieldnames or ()):
            raise ValueError('{} missing required fields {}'.format(path, required))
        for row in reader:
            key = int(row['key'])
            if key != len(counts):
                raise ValueError('{}: noncontiguous key {}, expected {}'.format(path, key, len(counts)))
            n = int(row['n_3d_success'])
            n2 = int(row['n_2d_filled'])
            slots = int(row['n_coordinate_slots'])
            if not (1 <= n <= n_slots and 0 <= n2 < n_slots and slots == n_slots and n + n2 == slots):
                raise ValueError('{}: invalid 3D/2D accounting on key {}'.format(path, key))
            counts.append(n)
            hist[n] += 1
            if n2 and first_2d is None:
                first_2d = key
    if len(counts) != n_records:
        raise ValueError('{}: found {}, expected {} records'.format(path, len(counts), n_records))
    return counts, hist, first_2d


def validate_lmdb_samples(lmdb_path, counts, first_2d, k=3):
    """Inspect actual existing records, never write to LMDB.

    Stored 3D slots are prefix; 2D fallback (if any) is suffix. For sampled
    fallback, require 2D suffix z coordinates flat. A genuine 3D molecule can
    accidentally be planar, so this does NOT reject 3D slots based on z-flatness.
    """
    import lmdb
    import numpy as np
    env = lmdb.open(str(lmdb_path), subdir=False, readonly=True, lock=False,
                    readahead=False, max_readers=32, max_spare_txns=1)
    checked = 0
    choices = {0, max(0, len(counts)//2), len(counts)-1}
    if first_2d is not None:
        choices.add(first_2d)
    if k > 3:
        for j in range(1, k-2):
            choices.add(int((len(counts)-1)*j/(k-1)))
    try:
        with env.begin(write=False) as txn:
            for key in sorted(choices):
                raw = txn.get(str(key).encode('ascii'))
                if raw is None:
                    raise ValueError('{}: LMDB key {} missing'.format(lmdb_path, key))
                rec = pickle.loads(raw)
                coords = rec.get('coordinates')
                atoms = rec.get('atoms')
                if coords is None or atoms is None or len(coords) != N_SLOTS or len(atoms) == 0:
                    raise ValueError('{} key {} record schema unexpected'.format(lmdb_path, key))
                for idx, conf in enumerate(coords):
                    a = np.asarray(conf)
                    if a.shape != (len(atoms),3) or not np.isfinite(a).all():
                        raise ValueError('{} key {} slot {} invalid shape/nonfinite'.format(lmdb_path,key,idx))
                    if idx >= counts[key] and not np.all(np.abs(a[:,2]) < 1e-4):
                        raise ValueError('{} key {}: claimed 2D suffix slot {} has nonflat z'.format(lmdb_path,key,idx))
                checked += 1
    finally:
        env.close()
    return checked


def prepare(src, dest, lmdb_sample=3, no_lmdb=False, full_lmdb_sha=False):
    src = src.resolve(strict=True)
    dest = dest.resolve()
    if dest == src or src in dest.parents or dest == src.parent or src.parent in dest.parents:
        raise ValueError('Output MUST be outside source lipid_library tree')
    if dest.exists():
        raise ValueError('Output already exists; refusing to overwrite: ' + str(dest))
    manifest, splits, qc, mh = check_sources(src)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix='.' + dest.name + '.partial-', dir=dest.parent))
    try:
        (tmp / 'slot_counts').mkdir()
        rows = []
        summary_hist = Counter()
        totals = Counter()
        for i, shard in enumerate(sorted(manifest['shards'], key=lambda s: s['shard_id'])):
            rel = rel_path(shard['lmdb'])
            lmdb_path = src / rel
            shard_dir = lmdb_path.parent
            receipt_path = shard_dir / 'shard.json'
            csv_path = shard_dir / 'records.csv.gz'
            if not lmdb_path.is_file() or not receipt_path.is_file() or not csv_path.is_file():
                raise ValueError('Missing input shard or receipt: {}'.format(shard_dir))
            receipt = load_json(receipt_path)
            if receipt.get('config_fingerprint') != manifest.get('config_fingerprint'):
                raise ValueError('Shard fingerprint mismatch: {}'.format(receipt_path))
            if int(receipt.get('n_records',-1)) != int(shard['n_records']):
                raise ValueError('Shard record count mismatch: {}'.format(shard_dir))
            csv_sha = sha256(csv_path)
            if not receipt.get('records_csv_sha256') or csv_sha != receipt['records_csv_sha256']:
                raise ValueError('Shard metadata CSV checksum mismatch: {}'.format(shard_dir))
            if lmdb_path.stat().st_size != int(shard.get('lmdb_bytes',lmdb_path.stat().st_size)):
                # Some old manifests lack lmdb_bytes; if defined, enforce it.
                raise ValueError('LMDB size differs from manifest: {}'.format(lmdb_path))
            if full_lmdb_sha and sha256(lmdb_path) != shard.get('lmdb_sha256'):
                raise ValueError('LMDB full SHA mismatch: {}'.format(lmdb_path))
            counts, hist, first_2d = read_index_csv(csv_path, int(shard['n_records']))
            samples = validate_lmdb_samples(lmdb_path, counts, first_2d, lmdb_sample) if not no_lmdb else 0
            outname = 'shard-{:05d}.bin'.format(shard['shard_id'])
            index_path = tmp / 'slot_counts' / outname
            index_path.write_bytes(counts)
            index_sha = sha256(index_path)
            n_fallback = len(counts) - hist.get(N_SLOTS,0)
            summary_hist.update(hist)
            totals['records'] += len(counts)
            totals['fallback_records'] += n_fallback
            totals['3d_slots'] += sum(k*v for k,v in hist.items())
            totals['lmdb_samples'] += samples
            rows.append({'shard_id':shard['shard_id'], 'lmdb':str(rel),
                         'lmdb_manifest_sha256':shard.get('lmdb_sha256'),
                         'records_csv_sha256':csv_sha, 'index': 'slot_counts/' + outname,
                         'index_sha256': index_sha, 'n_records':len(counts),
                         'n_fallback_records':n_fallback, 'sampled_lmdb_records':samples})
            if (i+1)%250==0 or i+1==len(manifest['shards']):
                print('Verified {}/{} shards; {:,} molecules'.format(i+1,len(manifest['shards']), totals['records']),flush=True)
        s4=qc.get('stage04',{})
        if (totals['records']!=manifest['n_records'] or
            totals['records'] != s4.get('n_records') or
            totals['fallback_records'] != s4.get('n_records_with_2d_fill') or
            totals['3d_slots'] != s4.get('n_3d_slots_total') or
            {str(k):v for k,v in summary_hist.items()} != {str(k):v for k,v in s4.get('n_3d_success_hist',{}).items()}):
            raise ValueError('Full per-record index does not agree with authoritative original production QC')
        if int(totals['records'])!=sum(int(s['n_records']) for s in manifest['shards']):
            raise ValueError('Manifest shard counts do not sum correctly')
        report = {
            'kind':'existing_Ugi_3d_prefix_index',
            'dataset':'original immutable LMDB shards referenced by source_lmdb_dir; index does not duplicate molecular records',
            'source_lmdb_dir':str(src),
            'source_manifest_sha256':mh,
            'source_splits_sha256':sha256(src/'splits.json'),
            'source_quality_report_sha256':sha256(src/'quality_report.json'),
            'source_original_quality_passed':qc.get('passed'),
            'source_original_quality_failures':qc.get('failures',[]),
            'coordinate_selection':'Only slots [0:n_3d_success) from authoritative Stage-04 CSV metadata; no heuristic filtering',
            'all_molecules_with_ge_1_3d_kept':True,
            'no_new_conformers_generated':True,
            'shard_count':len(rows),
            'stored_records':totals['records'],
            'fallback_containing_records_preserved':totals['fallback_records'],
            'record_with_all_10_3d_slots':totals['records']-totals['fallback_records'],
            'success_3d_slots_total':totals['3d_slots'],
            'n_3d_success_histogram':dict(sorted(summary_hist.items())),
            'sampled_real_lmdb_records':totals['lmdb_samples'],
            'all_3049_shard_metadata_csv_sha_verified':True,
            'all_shard_lmdb_sha_verified':bool(full_lmdb_sha),
            'data_index_validated':not no_lmdb,
            'production_continual_training_ready':False,
            'remaining_gate':'Integrate authoritative index into actual continual sampler + verify wrapper chain, then independent QC and full integrity verification',
            'shards':rows,
            'source_splits':{'train':splits['train'],'valid':splits['valid'],
                             'source_root':str(src), 'split_seed':splits.get('split_seed')},
        }
        (tmp / 'final_dataset_view.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n',encoding='utf-8')
        md=['# Ugi-4CR 3D-aware data index', '',
            '**Index verification:** {}'.format('PASS' if not no_lmdb else 'INCOMPLETE (metadata only)'),
            '**Original Stage 05 QC:** FAIL (unchanged)',
            '**Production continual-training ready:** NO', '',
            'Retained original source LMDB records: {:,}.'.format(totals['records']),
            'Records with at least one 2D fallback (preserved): {:,}.'.format(totals['fallback_records']),
            '3D slots across all records: {:,}.'.format(totals['3d_slots']),
            'Sampled actual LMDB records: {:,}.'.format(totals['lmdb_samples']),
            '', 'The index files contain one unsigned-byte n_3d_success per original record key.',
            'The eventual sampler must select slot 0 through n_3d_success-1 inclusive, NOT uniformly across all 10 slots.',
            'The original data and the QC report were not changed. Do not run Stage 06 yet.', '']
        (tmp/'final_dataset_view.md').write_text('\n\n'.join(md),encoding='utf-8')
        # Atomic publication; previous output never overwritten.
        os.rename(tmp,dest)
        print('DATA VIEW INDEX COMPLETE: {}'.format(dest))
        print('Source originals untouched, original QC={}, production training ready=NO'.format(qc.get('passed')))
        return report
    except BaseException:
        shutil.rmtree(tmp,ignore_errors=True)
        raise


def main():
    p=argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--lmdb-dir',required=True,type=Path)
    p.add_argument('--out-dir',required=True,type=Path)
    p.add_argument('--lmdb-samples',type=int,default=3)
    p.add_argument('--metadata-only',action='store_true', help='index build without LMDB record samples; NOT data-validated')
    p.add_argument('--full-lmdb-sha',action='store_true',help='slow full SHA256 of every existing LMDB (~hundreds of GB)')
    a=p.parse_args()
    if a.lmdb_samples<3:
        p.error('--lmdb-samples must be at least 3')
    try:
        prepare(a.lmdb_dir,a.out_dir,a.lmdb_samples,a.metadata_only,a.full_lmdb_sha)
    except Exception as exc:
        print('ABORT: {}'.format(exc),file=sys.stderr)
        return 2
    return 0

if __name__=='__main__':
    sys.exit(main())
