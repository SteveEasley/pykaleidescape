all: clean build

build:
	python3 -m build
	python -m twine upload -u __token__ dist/*

clean:
	rm dist/*