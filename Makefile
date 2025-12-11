all: clean build

test:
	pytest

check:
	ruff check kaleidescape tests --fix
	pylint kaleidescape tests

format:
	ruff format kaleidescape tests

mypy:
	mypy kaleidescape tests

build:
	python3 -m build
	python -m twine upload -u __token__ dist/*

clean:
	rm -rf dist build pykaleidescape.egg-info
