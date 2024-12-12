from setuptools import setup

setup(
    name="ahctools",
    version="0.1.0",
    description="AHCツール",
    author="titan23",
    author_email="titan23.kyopuro@gmail.com",
    license="特になし",
    url="https://github.com/titan-23/ahctools",
    packages=[
        "ahctools"
    ],  # パッケージ名が必要。プロジェクト構造に合わせて調整してください。
    install_requires=[],
    python_requires=">=3.10",
    keywords=["AtCoder", "AHC", "heuristic", "tools"],
)
