all: format check test

format:
	ruff format kaleidescape tests

check:
	mypy kaleidescape tests
	ruff check kaleidescape tests --fix
	pylint kaleidescape tests

test:
	pytest

build:
	python3 -m build
	python -m twine upload -u __token__ dist/*

clean:
	rm -rf dist build pykaleidescape.egg-info
