all: clean build

test:
	pytest

ruff:
	ruff check kaleidescape tests --fix
	ruff format kaleidescape tests

mypy:
	mypy kaleidescape tests

build:
	python3 -m build
	python -m twine upload -u __token__ dist/*

clean:
	rm dist/*
