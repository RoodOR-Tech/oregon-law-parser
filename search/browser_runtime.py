"""Fetch or verify the pinned, self-hosted Explorer Python runtime."""
import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen


def verify_runtime(directory, download=False):
    directory = Path(directory)
    lock = json.loads(Path(__file__).with_name('runtime-lock.json').read_text(encoding='utf-8'))
    for name, expected in lock['files'].items():
        path = directory / name
        if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == expected:
            continue
        if not download:
            raise ValueError('Missing or changed runtime file: ' + name)
        directory.mkdir(parents=True, exist_ok=True)
        with urlopen(lock['base_url'] + name, timeout=120) as response:
            data = response.read()
        if hashlib.sha256(data).hexdigest() != expected:
            raise ValueError('Runtime download checksum mismatch: ' + name)
        temporary = path.with_suffix(path.suffix + '.tmp')
        temporary.write_bytes(data)
        temporary.replace(path)
    return lock['version']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    print(verify_runtime(args.output, download=not args.verify_only))
