rm ./docs/ -r
rm ./_docs/_build/ -r

sphinx-build -b html ./_docs ./_docs/_build
cp -r ./_docs/_build/ ./docs/
