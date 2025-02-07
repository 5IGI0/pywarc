#!/bin/sh

virtualenv -p python3 .venv3
. .venv3/bin/activate

rm -rf build/ dist/
python setup.py bdist_wheel

twine upload dist/*