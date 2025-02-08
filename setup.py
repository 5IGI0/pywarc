from setuptools import setup, find_packages
from pywarc.constants import PY_WARC_VERSION

setup(
    name="pywarc",
    version=PY_WARC_VERSION,
    packages=["pywarc"],
    install_requires=[],
    author="5IGI0",
    author_email="5IGI0@protonmail.com",
    description="WARC file format library",
    long_description=open('README.md').read(),
    long_description_content_type='text/markdown',
    url="https://github.com/5IGI0/pywarc",
    classifiers=[
        "Programming Language :: Python :: 3",
        "Operating System :: OS Independent",
    ],
    python_requires='>=3.7',
)