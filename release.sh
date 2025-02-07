#!/bin/sh

virtualenv -p python3 .venv3
. .venv3/bin/activate
python setup.py bdist_wheel

twine upload dist/*