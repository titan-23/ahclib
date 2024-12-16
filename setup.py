from setuptools import setup
from pathlib import Path

setup(
    name="ahclib",
    version="0.1.6",
    description="Parallel Execution and Optuna Optimization Tools for AHC",
    author="titan23",
    author_email="titan23.kyopuro@gmail.com",
    long_description=(Path(__file__).parent / "README.rst").read_text(),
    long_description_content_type="text/x-rst",
    license="MIT License",
    url="https://github.com/titan-23/ahclib",
    packages=["ahclib"],
    install_requires=[],
    python_requires=">=3.10",
    keywords=["AtCoder", "AHC", "heuristic"],
)
