#!/bin/sh
set -eu

cd "$(dirname "$0")"

[ -d .venv3 ] || virtualenv -p python3 .venv3
. .venv3/bin/activate

python -m pip install --upgrade pip build twine

rm -rf build/ dist/ *.egg-info
python -m build

twine check dist/*
twine upload dist/*
