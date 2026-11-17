#!/usr/bin/env python3
"""Read-only audit of an ALREADY FINALIZED Ugi-4CR lipid library.

This is NOT a replacement for the original Stage-05 quality gate, an integrity
verification, or a license to launch continual training. It only reads Stage-04
receipts/Stage-05 reports and writes separate reports OUTSIDE LMDB_DIR.

Usage from model/pretrain:
  python -m lipid_library.audit_existing_3d \
    /project/yli4/ypan/lipid_library/lmdb \
    --out-dir /project/yli4/ypan/audits/ugi_3d_readiness
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys


def load(path):
    with path.open('r', encoding='utf-8') as f:
        return json.load(f)


def sha256_file(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def analyze(lmdb_dir):
    lmdb_dir = Path(lmdb_dir).resolve(strict=True)
    files = {name: lmdb_dir / name for name in ('manifest.json', 'splits.json',
                                                'quality_report.json', 'validation.json',
                                                'finalize_report.json')}
    missing = [str(p) for p in files.values() if not p.is_file()]
    if missing:
        raise ValueError('Cannot audit incomplete Stage 05 metadata: ' + ', '.join(missing))
    manifest, splits, qc = load(files['manifest.json']), load(files['splits.json']), load(files['quality_report.json'])
    validation, finalize = load(files['validation.json']), load(files['finalize_report.json'])
    manifest_sha = sha256_file(files['manifest.json'])
    problems = []
    if not manifest.get('complete') or not finalize.get('complete'):
        problems.append('Manifest or finalize report is incomplete')
    if splits.get('manifest_sha256') != manifest_sha:
        problems.append('Splits manifest hash mismatch')
    if qc.get('manifest_sha256') != manifest_sha:
        problems.append('Quality report manifest hash mismatch')
    if finalize.get('config_fingerprint') != manifest.get('config_fingerprint'):
        problems.append('Finalize configuration fingerprint mismatch')
    if validation.get('n_problems') != 0:
        problems.append('Stage 05 validation has reported problems')
    if manifest.get('smoke') or splits.get('smoke'):
        problems.append('Library is smoke/partial, not production')
    shards = manifest.get('shards', [])
    if manifest.get('n_shards') is not None and len(shards) != manifest['n_shards']:
        problems.append('Shard count disagrees with manifest')
    absent = []
    for shard in shards:
        rel = shard.get('lmdb')
        if not rel or Path(rel).is_absolute() or '..' in Path(rel).parts:
            problems.append('Unsafe/invalid shard reference in manifest')
            break
        p = lmdb_dir / rel
        csv_path = p.parent / 'records.csv.gz'
        if not p.is_file() or not csv_path.is_file():
            absent.append(str(p.parent))
    if absent:
        problems.append('{} shard(s) missing LMDB or per-record metadata (first: {})'.format(len(absent), absent[:3]))
    s4 = qc.get('stage04', {})
    n = int(s4.get('n_records') or 0)
    fallback = int(s4.get('n_records_with_2d_fill') or 0)
    hist = {str(k): int(v) for k, v in (s4.get('n_3d_success_hist') or {}).items()}
    hist_count = sum(hist.values())
    if not n or not hist or hist_count != n:
        problems.append('Global 3D-success histogram is missing or inconsistent with n_records')
    if fallback > n:
        problems.append('Fallback records exceed stored records')
    clean = n - fallback
    if int(hist.get('10', 0)) != clean:
        problems.append('10-success conformer count differs from zero-fallback record count')
    nonzero = sum(v for k, v in hist.items() if int(k) >= 1)
    if nonzero != n:
        problems.append('Stored records include zero-success 3D conformers or histogram is inconsistent')
    if int(manifest.get('n_records') or -1) != n:
        problems.append('Manifest count differs from QC stored count')
    is_original_qc_fail = qc.get('passed') is not True
    flags = {
        'original_quality_passed': qc.get('passed'),
        'original_quality_failures': qc.get('failures', []),
        'original_library_ready_exists': (lmdb_dir / 'library_ready.json').is_file(),
        'all_stage05_metadata_consistent': not problems,
        'sampler_3d_slot_aware_verified': False,
        'lnpdb_integration_finalized': False,
        'continual_production_ready': False,
    }
    # This reports the *possibilities* only; it does not create an index or change a sampler.
    return {
        'audit_kind': 'non_destructive_existing_stage05_3d_review',
        'source_lmdb_dir': str(lmdb_dir),
        'source_manifest_sha256': manifest_sha,
        'original_qc_failed': is_original_qc_fail,
        'data_counts': {'stored_records': n, 'records_containing_2d_fallback': fallback,
                        'full_3d_slot_records_if_filtered': clean,
                        'percent_records_retained_if_filtered': (100.0 * clean / n) if n else None,
                        'all_stored_records_have_at_least_one_3d_slot': nonzero == n,
                        '3d_success_histogram': hist,
                        'n_2d_filled_total': s4.get('n_2d_filled_total'),
                        'mean_distinct_3d_per_record': s4.get('mean_distinct_3d_per_record')},
        'validation': {'original_validation_problems': validation.get('n_problems'),
                       'audited_shards': len(shards), 'metadata_errors': problems},
        'flags': flags,
        'design_notes': [
            'Lipid writer places valid 3D conformers FIRST, then 2D fill-in slots; '
            'the per-record records.csv.gz provides n_3d_success; verify alignment '
            'with LMDB before implementing a training sampler.',
            '10 coordinate slots need not be 10 distinct conformers.',
            'Filtering every fallback-containing record may introduce molecular-structure bias.',
            'Existing ConformerSampleDataset samples uniformly from ALL slots; unsafe for mixed records.',
            'This audit DOES NOT scan every LMDB record or validate each LMDB SHA-256.',
            'Neither an existing QC failure nor a missing library_ready.json is overridden.',
            'Future LNPDB mixing and production sampler remain undecided.',
        ],
    }


def render_md(rep):
    d, flags = rep['data_counts'], rep['flags']
    lines = [
        '# Existing lipid library — non-destructive 3D audit', '',
        '**PRODUCTION STATUS: NOT READY.** This is a decision-support audit only.', '',
        'Original QC passed: `{}`; original library_ready exists: `{}`.'.format(
            flags['original_quality_passed'], flags['original_library_ready_exists']), '',
        '| Metric | Value |', '|---|---:|',
        '| Stored records | {:,} |'.format(d['stored_records']),
        '| Records with any 2D fill-in | {:,} |'.format(d['records_containing_2d_fallback']),
        '| Possible full-3D-slot records if filtered | {:,} |'.format(d['full_3d_slot_records_if_filtered']),
        '| Possible retained fraction | {:.3f}% |'.format(d['percent_records_retained_if_filtered'] or 0.0),
        '| Mean distinct 3D / record (all records) | {} |'.format(d['mean_distinct_3d_per_record']),
        '', '## Stage 04 histogram (authoritative aggregate from original quality report)', '',
        '| Successful 3D slots | Records |', '|---:|---:|',
    ]
    for k, v in sorted(d['3d_success_histogram'].items(), key=lambda x: int(x[0])):
        lines.append('| {} | {:,} |'.format(k, v))
    lines += ['', '## Validation warnings', '']
    lines += ['- ' + x for x in rep['validation']['metadata_errors']] or ['- No report/manifest inconsistency detected; shard content checksums NOT executed.']
    lines += ['', '## Open design decisions (no code/data changes performed)', '']
    lines += ['- ' + x for x in rep['design_notes']]
    lines += ['', '**Do not run production Stage 05 finalize again or start continual pretraining from this audit.**', '']
    return '\n'.join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('lmdb_dir')
    ap.add_argument('--out-dir', required=True, help='report directory, separate from production LMDB')
    args = ap.parse_args(argv)
    src = Path(args.lmdb_dir).resolve(strict=True)
    out = Path(args.out_dir).resolve()
    if out == src or src in out.parents:
        ap.error('audit reports must NOT be written into the original LMDB tree')
    if out == src.parent or src.parent in out.parents:
        # Audit output in the sibling Project audits directory is preferred; never inside lipid_library.
        ap.error('audit output must live outside the lipid_library root')
    report = analyze(src)
    if report['validation']['metadata_errors']:
        print('ABORT — input metadata inconsistent: {}'.format(report['validation']['metadata_errors']), file=sys.stderr)
        return 2
    out.mkdir(parents=True, exist_ok=True)
    (out / 'existing_3d_audit.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    (out / 'existing_3d_audit.md').write_text(render_md(report), encoding='utf-8')
    print('READ-ONLY INPUT AUDIT COMPLETE: {} stored, {} fallback records, {} full-3D-slot records'.format(
        report['data_counts']['stored_records'], report['data_counts']['records_containing_2d_fallback'],
        report['data_counts']['full_3d_slot_records_if_filtered']))
    print('Original QC: {}; continual ready: NO'.format(report['flags']['original_quality_passed']))
    print('Reports: {}'.format(out))
    return 0


if __name__ == '__main__':
    sys.exit(main())
