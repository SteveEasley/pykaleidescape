all: clean build

test:
	pytest -v tests/

ruff:
	ruff check kaleidescape tests --fix

mypy:
	mypy kaleidescape tests

build:
	python3 -m build
	python -m twine upload -u __token__ dist/*

clean:
	rm dist/*
