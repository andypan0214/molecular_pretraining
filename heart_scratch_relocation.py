#!/usr/bin/env python3
"""HEART v2 verified Home -> Scratch relocation (does not rewrite shard metadata).

Usage (run from any working directory on CMRI HPC):
    python heart_scratch_relocation.py                 # validation, preview only
    python heart_scratch_relocation.py --apply         # patch Scratch checkout only

The helper preserves the original scientific config fingerprints by resolving a
verified relocation of the *identity* of a drop-list path, while actual input is
always opened from Scratch. All original locks and shard receipts stay untouched.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import textwrap

OLD_BASE = Path('/home/ypan/heart_liver/model_train')
NEW_BASE = Path('/scratch/ypan/heart_liver/model_train')
DROP_REL = Path('lipid_library/dedup/drop_combo_indexes.csv.gz')
REPO_REL = Path('heart-molecular-pretraining-v2')
FILE_REL = Path('model/pretrain/lipid_library/lmdb_writer.py')
HELPER_REL = Path('model/pretrain/lipid_library/_scratch_relocation_identity.py')
CONFIG_REL = Path('config/heart_v2_scratch.yaml')
LOCK_REL = Path('lipid_library/lmdb/lmdb_writer_config.json')
PART_LOCK_REL = Path('lipid_library/lmdb/shard_inputs/partition_config.json')
PART_INDEX_REL = Path('lipid_library/lmdb/shard_inputs/partition_index.json')


def die(s):
    raise RuntimeError(s)


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def digest_config(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(',', ':'), default=str).encode()).hexdigest()


def read_json(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def verify_lock(path):
    lock = read_json(path)
    if not isinstance(lock.get('config'), dict) or not isinstance(lock.get('fingerprint'), str):
        die('Malformed provenance lock: ' + str(path))
    if digest_config(lock['config']) != lock['fingerprint']:
        die('Saved provenance lock is not self-consistent: ' + str(path))
    return lock


def validate():
    # We deliberately do not require OLD_BASE to exist: original data may have
    # already been cleaned up. The immutable historical lock plus actual
    # scratch content hashes are the authoritative evidence.
    new_drop = NEW_BASE / DROP_REL
    repo = NEW_BASE / REPO_REL
    lmdb_dir = NEW_BASE / 'lipid_library/lmdb'
    code = repo / FILE_REL
    for path in (new_drop, code, NEW_BASE / LOCK_REL, NEW_BASE / PART_LOCK_REL,
                 NEW_BASE / PART_INDEX_REL, NEW_BASE / 'lipid_library/enum/enumeration_complete.json',
                 NEW_BASE / 'UniMolReference/ligand_data/ligands/dict.txt'):
        if not path.is_file():
            die('Missing required Scratch file: ' + str(path))
    if not repo.resolve().is_relative_to(NEW_BASE.resolve()):
        die('Repository is not inside designated Scratch tree')
    if not (repo / 'bin/heart').is_file():
        die('Wrong checkout: bin/heart missing')

    writer = verify_lock(NEW_BASE / LOCK_REL)
    part = verify_lock(NEW_BASE / PART_LOCK_REL)
    index = read_json(NEW_BASE / PART_INDEX_REL)
    old_drop = str(OLD_BASE / DROP_REL)
    new_drop_str = str(new_drop)
    actual_drop_sha = sha256(new_drop)
    if writer['config'].get('drop_list') != old_drop or part['config'].get('drop_list') != old_drop:
        die('Unexpected legacy drop-list location in locks; will not rewrite provenance')
    if writer['config'].get('drop_list_sha256') != actual_drop_sha:
        die('Scratch drop-list SHA differs from saved writer config')
    if part['config'].get('drop_list_sha256') != actual_drop_sha:
        die('Scratch drop-list SHA differs from saved partition config')
    if index.get('config_fingerprint') != part['fingerprint'] or index.get('complete') is not True:
        die('Partition index is incomplete or disagrees with partition lock')

    with open(NEW_BASE / 'lipid_library/enum/enumeration_complete.json', encoding='utf8') as f:
        enumeration = json.load(f)
    enum_fp = enumeration.get('config_fingerprint')
    if writer['config'].get('enumeration_fingerprint') != enum_fp or part['config'].get('enumeration_fingerprint') != enum_fp:
        die('Enumeration fingerprint mismatch')
    if writer['config'].get('enumeration_complete_sha256') != sha256(NEW_BASE / 'lipid_library/enum/enumeration_complete.json'):
        die('Enumeration complete receipt changed')
    if part['config'].get('enumeration_complete_sha256') != writer['config'].get('enumeration_complete_sha256'):
        die('Partition and writer enumeration hashes differ')
    if writer['config'].get('dict_sha256') != sha256(NEW_BASE / 'UniMolReference/ligand_data/ligands/dict.txt'):
        die('Scratch dictionary changed')
    if writer['config'].get('n_3d') != 10 or writer['config'].get('records_per_shard') != 5000:
        die('Unexpected scientific configuration; manual review required')

    receipts = list(lmdb_dir.glob('shard-*/shard.json'))
    for receipt_path in receipts:
        receipt = read_json(receipt_path)
        if receipt.get('config_fingerprint') != writer['fingerprint']:
            die('Shard has different configuration fingerprint: ' + str(receipt_path))
        if not (receipt_path.parent / 'train.lmdb').is_file():
            die('Shard receipt missing train.lmdb: ' + str(receipt_path))
    print('Verified locked writer fingerprint: ', writer['fingerprint'])
    print('Verified locked partition fingerprint:', part['fingerprint'])
    print('Verified Scratch drop-list SHA-256:    ', actual_drop_sha)
    print('Found shard receipts:', len(receipts))
    print('Actual data path:', new_drop_str)
    print('Historical provenance path:', old_drop)
    print('NOTE: full LMDB SHA verification remains the job preflight/Stage 05 responsibility.')
    return {'repo': repo, 'new_drop': new_drop_str, 'old_drop': old_drop,
            'drop_sha': actual_drop_sha, 'writer_fp': writer['fingerprint'],
            'partition_fp': part['fingerprint']}


def make_helper(v):
    # The helper only alters provenance's historical path label. It never
    # changes the physical file used by the writer to read drop indexes.
    return textwrap.dedent('''\
        """Verified path-identity compatibility for migrated HEART lipid library.

        Generated by heart_scratch_relocation.py. Historical locks/receipts
        are immutable. Only a pinned Scratch copy with matching SHA is allowed.
        """
        import hashlib
        from pathlib import Path

        _ACTUAL = Path({actual!r})
        _LEGACY = {legacy!r}
        _SHA256 = {sha!r}

        def historical_drop_identity(actual_path, current_sha):
            path = Path(actual_path)
            if str(path) != str(_ACTUAL):
                return str(path)  # Other output roots follow the original code.
            if current_sha != _SHA256:
                raise ValueError('Scratch drop-list SHA differs from attested migration')
            h = hashlib.sha256()
            with path.open('rb') as f:
                for data in iter(lambda: f.read(8 * 1024 * 1024), b''):
                    h.update(data)
            if h.hexdigest() != _SHA256:
                raise ValueError('Scratch drop-list changed after migration')
            return _LEGACY
        ''').format(actual=v['new_drop'], legacy=v['old_drop'], sha=v['drop_sha'])


def patch_code(original):
    anchor = '''    return {"drop_list": os.path.abspath(drop_list), "drop_list_sha256": io_utils.sha256_file(drop_list),
            "dedup_enumeration_fingerprint": dedup_fp}'''
    replacement = '''    # Relocation-aware *identity* only; actual file reads use opts.drop_list (Scratch).
    from ._scratch_relocation_identity import historical_drop_identity
    drop_sha = io_utils.sha256_file(drop_list)
    historical_label = historical_drop_identity(os.path.abspath(drop_list), drop_sha)
    return {"drop_list": historical_label, "drop_list_sha256": drop_sha,
            "dedup_enumeration_fingerprint": dedup_fp}'''
    if original.count(anchor) != 1:
        die('Cannot safely patch this lmdb_writer.py version; expected anchor not found exactly once')
    return original.replace(anchor, replacement)


def make_config(repo):
    try:
        import yaml
    except ImportError:
        die('PyYAML needed to create config; activate heart_gpu')
    source = repo / 'config/heart_v2.yaml'
    cfg = yaml.safe_load(source.read_text(encoding='utf-8'))
    for k, value in cfg['paths'].items():
        if isinstance(value, str) and value.startswith(str(OLD_BASE) + '/'):
            cfg['paths'][k] = str(NEW_BASE) + value[len(str(OLD_BASE)):]
    # Crucially leave environment.conda_env under /home unchanged.
    return '# Scratch-only configuration. Original config untouched.\n' + yaml.safe_dump(cfg, sort_keys=False)


def apply(v):
    repo = v['repo']
    code_path = repo / FILE_REL
    helper_path = repo / HELPER_REL
    cfg_path = repo / CONFIG_REL
    src = code_path.read_text(encoding='utf-8')
    dest = patch_code(src)
    helper = make_helper(v)
    cfg = make_config(repo)
    if helper_path.exists() or cfg_path.exists():
        die('Scratch relocation helper/config already exists; no files changed. Review them first.')
    backup = code_path.with_name(code_path.name + '.before_scratch_relocation.bak')
    if backup.exists():
        die('Backup already exists; refusing second patch')
    # Preflight compilation before any write.
    compile(dest, str(code_path), 'exec')
    compile(helper, str(helper_path), 'exec')
    # Create recoverable original before writing patched version.
    shutil.copy2(code_path, backup)
    helper_path.write_text(helper, encoding='utf-8')
    cfg_path.write_text(cfg, encoding='utf-8')
    code_path.write_text(dest, encoding='utf-8')
    print('\nPATCH APPLIED to Scratch only:')
    print(' ', code_path)
    print(' ', helper_path)
    print(' ', cfg_path)
    print('Original code backup:', backup)
    print('No LMDB, shard, receipt, lock or Home file was modified.')
    print('Next: cd', repo)
    print('      bin/heart --config config/heart_v2_scratch.yaml library --resume --dry-run')
    print('      # Check preflight on a compute allocation before production submit.')
    print('      bin/heart --config config/heart_v2_scratch.yaml library --resume --submit')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--apply', action='store_true', help='Patch Scratch copy after validation')
    args = ap.parse_args()
    v = validate()
    if args.apply:
        apply(v)
    else:
        code_path = v['repo'] / FILE_REL
        patch_code(code_path.read_text(encoding='utf-8'))
        print('\nPREVIEW PASS. No changes made. Run with --apply to patch Scratch only.')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        sys.exit('ERROR (no intentional changes after failed validation): ' + str(exc))
