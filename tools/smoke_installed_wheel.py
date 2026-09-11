"""Install the built wheel in a fresh environment and run outside the checkout."""
import argparse
from pathlib import Path
import subprocess
import sys
import tempfile
import venv


def main():
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument('--wheel', type=Path, required=True)
    args.add_argument('--manifest', type=Path, required=True)
    options = args.parse_args()
    with tempfile.TemporaryDirectory(prefix='ors-wheel-') as temporary:
        root = Path(temporary)
        environment = root/'environment'
        venv.EnvBuilder(with_pip=True, system_site_packages=True).create(environment)
        python = environment/('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
        subprocess.run([str(python), '-m', 'pip', 'install', '--no-deps', str(options.wheel.resolve())], check=True)
        subprocess.run([str(python), '-c',
            "import parser,ors,sys; from pathlib import Path; "
            "assert Path(parser.__file__).is_relative_to(Path(sys.prefix)); "
            "assert Path(ors.__file__).is_relative_to(Path(sys.prefix))"], cwd=root, check=True)
        subprocess.run([str(python), '-m', 'parser.cli', 'run', '--year', '2023',
            '--manifest', str(options.manifest.resolve()), '--output', str(root/'ors.db'), '--quiet'], cwd=root, check=True)


if __name__ == '__main__':
    main()
