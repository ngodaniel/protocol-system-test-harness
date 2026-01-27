.PHONY: lint type test-smoke test-system test-all

lint:
	python -m ruff check .

type:
	python -m mypy src

test-smoke:
	python -m pytest -m smoke -- junitxml=artifacts/junit-smoke.xml --html=artifacts/smoke.html -- self-contained-html

test-system:
	python -m pytest -m system --junitxml=artifacts/junit-system.xml --html=artifacts/system.html --self-contained-html

test-all:
	python -m pytest --junitxml=artifacts/junit-all.xml --html=artifacts/all.html --self-contained-html
	