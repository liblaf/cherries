default: gen-init lint

build:
    rm --force --recursive dist/
    pyproject-build
    check-wheel-contents dist/*.whl
    twine check --strict dist/*

gen-init:
    ./scripts/gen-init.sh

lint: lint-toml lint-python

lint-python:
    ruff format
    ruff check --fix

lint-toml:
    sort-toml .ruff.toml pyproject.toml

test:
    pytest

upgrade:
    pixi upgrade
    just lint
