from glob import glob
from os.path import basename, splitext
from setuptools import setup, find_packages


def _requires_from_file(filename: str):
    return open(filename).read().splitlines()


setup(
    name="ahctools",
    version="0.1.0",
    license="特になし",
    description="AHCツール",
    author="titan23",
    url="https://github.com/titan-23/ahctools",
    packages=find_packages("ahctools"),
    package_dir={"": "ahctools"},
    py_modules=[splitext(basename(path))[0] for path in glob("ahctools/*.py")],
    include_package_data=True,
    zip_safe=False,
    install_requires=_requires_from_file("requirements.txt"),
)
