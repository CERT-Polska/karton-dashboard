#!/usr/bin/env python
try:
    from setuptools import setup
except ImportError:
    from distutils.core import setup

from pathlib import Path

version_path = Path(__file__).parent / "karton/dashboard/__version__.py"
version_info = {}
exec(version_path.read_text(), version_info)

setup(
    name="karton-dashboard",
    version=version_info["__version__"],
    description="A small Flask application that allows for Karton task and queue introspection.",
    namespace_packages=["karton"],
    packages=["karton.dashboard"],
    install_requires=open("requirements.txt").read().splitlines(),
    include_package_data=True,
    entry_points={
        'console_scripts': [
            'karton-dashboard=karton.dashboard:cli'
        ],
    },
    classifiers=[
        "Programming Language :: Python",
        "Operating System :: OS Independent",
    ],
)
