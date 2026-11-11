#!/usr/bin/env python3
"""One-time, local-only HEART v2 Scratch relocation patch.

Use on the SCRATCH checkout with heart_gpu Python. Nothing in /home is edited.
Default is verification/preview. Pass --apply to write a Scratch-only config
and patch the Scratch checkout's lipid_library/lmdb_writer.py.

The patch intentionally preserves legacy *identity* in existing fingerprints,
while reading input files from Scratch. It never rewrites scientific receipts.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

OLD_BASE = '/home/ypan/heart_liver/model_train'
NEW_BASE = '/scratch/ypan/heart_liver/model_train'
MARKER = '# HEART_SCRATCH_RELOCATION_V1'


def fingerprint(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(',', ':'), default=str).encode()).hexdigest()


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def load_lock(path):
    d = json.loads(path.read_text())
    if not isinstance(d.get('config'), dict) or not isinstance(d.get('fingerprint'), str):
        raise RuntimeError(f'Invalid lock: {path}')
    actual = fingerprint(d['config'])
    if actual != d['fingerprint']:
        raise RuntimeError(f'Lock fingerprint mismatch: {path}: {actual} != {d["fingerprint"]}')
    return d


def validate(base):
    root = base / 'lipid_library'
    lmdb = root / 'lmdb'
    writer_lock = load_lock(lmdb / 'lmdb_writer_config.json')
    partition_lock = load_lock(lmdb / 'shard_inputs' / 'partition_config.json')
    orig = OLD_BASE + '/lipid_library/dedup/drop_combo_indexes.csv.gz'
    relocated = root / 'dedup' / 'drop_combo_indexes.csv.gz'
    if not relocated.is_file():
        raise RuntimeError(f'Missing Scratch drop list: {relocated}')
    digest = sha256_file(relocated)
    for name, record in [('writer', writer_lock), ('partition', partition_lock)]:
        cfg = record['config']
        if cfg.get('drop_list') != orig:
            raise RuntimeError(f'{name} lock has unexpected path: {cfg.get("drop_list")!r} (expected {orig!r})')
        if cfg.get('drop_list_sha256') != digest:
            raise RuntimeError(f'{name} lock SHA differs from actual Scratch input')
    if writer_lock['config'].get('enumeration_fingerprint') != partition_lock['config'].get('enumeration_fingerprint'):
        raise RuntimeError('Enumeration fingerprint differs between writer and partition locks')
    if writer_lock['config'].get('dedup_enumeration_fingerprint') != partition_lock['config'].get('dedup_enumeration_fingerprint'):
        raise RuntimeError('Dedup fingerprint differs between writer and partition locks')
    # Also ensure the stored integrity hash for the general dict is preserved.
    dict_path = base / 'UniMolReference/ligand_data/ligands/dict.txt'
    if sha256_file(dict_path) != writer_lock['config'].get('dict_sha256'):
        raise RuntimeError('Scratch dict.txt SHA mismatch')
    print('PASS: writer and partition lock self-hashes, scratch drop-list SHA, enumeration fingerprints, dict SHA')
    print('Locked writer fingerprint:', writer_lock['fingerprint'])
    print('Locked partition fingerprint:', partition_lock['fingerprint'])
    return root, orig, digest


# Injected helper only changes the path string used for provenance hashing.
# Physical drop_list files always remain at the passed Scratch location.
PATCH = '''\n\n{marker}\ndef _heart_relocation_drop_identity(drop_list):
    """Keep verified pre-move drop-list identity (not the physical read path)."""
    current = os.path.abspath(drop_list)
    if not current.startswith({newprefix!r}):
        return current
    libroot = os.path.dirname(os.path.dirname(current))
    if current != os.path.join(libroot, 'dedup', 'drop_combo_indexes.csv.gz'):
        return current
    locks = [
        os.path.join(libroot, 'lmdb', 'lmdb_writer_config.json'),
        os.path.join(libroot, 'lmdb', 'shard_inputs', 'partition_config.json'),
    ]
    if not all(os.path.isfile(p) for p in locks):
        return current
    legacy = {old_drop!r}
    actual_digest = io_utils.sha256_file(current)
    for lock_path in locks:
        with open(lock_path, encoding='utf-8') as fh:
            locked = json.load(fh)
        config = locked['config']
        if provenance.fingerprint(config) != locked['fingerprint']:
            raise provenance.StaleOutputError('Corrupt relocation lock: ' + lock_path)
        if config.get('drop_list') != legacy or config.get('drop_list_sha256') != actual_digest:
            raise provenance.StaleOutputError('Relocation lock does not match Scratch input: ' + lock_path)
    return legacy
'''


def patch_code(base, legacy, apply):
    repo = base / 'heart-molecular-pretraining-v2'
    src = repo / 'model/pretrain/lipid_library/lmdb_writer.py'
    old = src.read_text()
    needle = '"drop_list": os.path.abspath(drop_list), "drop_list_sha256": io_utils.sha256_file(drop_list),'
    replacement = '"drop_list": _heart_relocation_drop_identity(drop_list), "drop_list_sha256": io_utils.sha256_file(drop_list),'
    if MARKER in old:
        if replacement not in old:
            raise RuntimeError('Relocation marker found but expected replacement missing')
        print('Already patched:', src)
        return
    if old.count(needle) != 1:
        raise RuntimeError(f'Expected EXACTLY one drop-list identity expression, found {old.count(needle)}; abort')
    patched = old.replace(needle, replacement)
    main_guard = 'if __name__ == "__main__":'
    if patched.count(main_guard) != 1:
        raise RuntimeError('Cannot find unique __main__ guard; abort')
    content = patched.replace(main_guard, PATCH.format(marker=MARKER, newprefix=str(base) + '/', old_drop=legacy) + '\n\n' + main_guard)
    compile(content, str(src), 'exec')
    print('Will patch only Scratch source:', src)
    if apply:
        backup = src.with_name(src.name + '.before_scratch_relocation.bak')
        if backup.exists():
            raise RuntimeError(f'Backup already exists and source is not patched: {backup}; abort')
        shutil.copy2(src, backup)
        src.write_text(content)
        print('Wrote patch; original local source backed up:', backup)


def make_config(base, apply):
    repo = base / 'heart-molecular-pretraining-v2'
    original = repo / 'config/heart_v2.yaml'
    dest = repo / 'config/heart_v2_scratch.yaml'
    import yaml
    cfg = yaml.safe_load(original.read_text())
    for key, value in cfg['paths'].items():
        if isinstance(value, str) and value.startswith(OLD_BASE):
            cfg['paths'][key] = str(base) + value[len(OLD_BASE):]
    if any(isinstance(v, str) and v.startswith(OLD_BASE) for v in cfg['paths'].values()):
        raise RuntimeError('Not all model_train path entries were relocated')
    print('Scratch config path:', dest)
    print('Conda environment untouched:', cfg['environment']['conda_env'])
    if apply:
        if dest.exists():
            existing = yaml.safe_load(dest.read_text())
            if existing != cfg:
                raise RuntimeError('Scratch config exists and differs: refusing to overwrite')
        else:
            dest.write_text('# Local Scratch paths; original heart_v2.yaml unchanged\n' + yaml.safe_dump(cfg, sort_keys=False))
            print('Created:', dest)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base', default=NEW_BASE)
    p.add_argument('--apply', action='store_true')
    args = p.parse_args()
    base = Path(args.base).resolve()
    if str(base) != NEW_BASE:
        raise RuntimeError(f'For safety this script only supports {NEW_BASE}')
    if not (base / 'heart-molecular-pretraining-v2/bin/heart').exists():
        raise RuntimeError('HEART v2 checkout missing at Scratch location')
    root, legacy, _ = validate(base)
    make_config(base, args.apply)
    patch_code(base, legacy, args.apply)
    print('\nDONE: ' + ('Scratch code/config patched, no jobs submitted.' if args.apply else 'Preview only; rerun with --apply.'))
    print('Next: cd ' + str(base / 'heart-molecular-pretraining-v2'))
    print('Then: bin/heart --config config/heart_v2_scratch.yaml library --resume --dry-run')
    print('Submit only after preflight passes; stage 05 may still fail QC until library quality is addressed.')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        sys.exit('ERROR (no intentional changes after failed validation): ' + str(exc))
