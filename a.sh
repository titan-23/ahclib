sudo rm -r dist
sudo rm -r build
sudo rm -r ahclib.egg-info

python3 -m build
# python3 -m twine upload --repository testpypi dist/* --verbose

# 本番環境
# python3 -m twine upload --repository pypi dist/* --verbose
