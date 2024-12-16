from setuptools import setup
from pathlib import Path

long_description = (Path(__file__).parent / "README.rst").read_text()

setup(
    name="ahclib",
    version="0.1.3",
    description="AHCのための並列実行とoptuna最適化ツール",
    author="titan23",
    author_email="titan23.kyopuro@gmail.com",
    long_description=long_description,
    long_description_content_type="text/x-rst",
    license="MIT License",
    url="https://github.com/titan-23/ahclib",
    packages=["ahclib"],
    install_requires=[],
    python_requires=">=3.10",
    keywords=["AtCoder", "AHC", "heuristic"],
)
