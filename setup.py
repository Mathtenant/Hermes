"""Setup shim for hermes-assistant — package discovery only.

Name, version and every other distribution field come from ``[project]`` in
pyproject.toml, which setuptools reads as the authoritative source. They are
deliberately NOT repeated here: a second copy of the version would drift
silently from ``hermes_assistant.__version__`` and ship a stale number in the
wheel metadata. This file exists only because there is no
``[tool.setuptools]`` table declaring the src-layout package discovery.
"""

from setuptools import find_packages, setup

setup(
    packages=find_packages(where="src"),
    package_dir={"": "src"},
)
