# One entry point for every routine task. Everything runs in the pipeline image (./pipe), so results do not
# depend on the host Python. `make help` lists the targets.
.DEFAULT_GOAL := help
.PHONY: help build lint format test test-unit e2e report pipeline dag status stack-up stack-down demo

help:            ## list the targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-16s %s\n", $$1, $$2}'

build:           ## build the pipeline image (Python, Java, Spark, Ray)
	./pipe build

lint:            ## PEP 8 and import order (ruff, the rules in pyproject.toml)
	./pipe ruff check .
	./pipe ruff format --check .

format:          ## apply the formatter
	./pipe ruff format .

test:            ## every test (unit, integration, API)
	./pipe pytest -q -p no:cacheprovider

test-unit:       ## fast tests only
	./pipe pytest -q -p no:cacheprovider tests/unit

e2e:             ## end-to-end tests against the running stack (./stack up -d first)
	./pipe bash -c "E2E_API_URL=http://127.0.0.1:8000 pytest -q -p no:cacheprovider tests/e2e"

report:          ## run every test and write reports/test_report.md
	./pipe python scripts/test_report.py

pipeline:        ## rerun every out-of-date DVC stage (the frozen evaluate stage never reruns)
	./pipe dvc repro

dag:             ## print the pipeline graph
	./pipe dvc dag

status:          ## which stages are out of date
	./pipe dvc status

stack-up:        ## build and start the serving and monitoring stack
	./stack up -d --build

stack-down:      ## stop the stack (data and volumes stay)
	./stack down

demo:            ## replay validation days through the API so Grafana moves
	./stack --profile demo up -d replay

mlproject-test:  ## run the test entry point through MLflow Projects (needs mlflow on the host)
	mlflow run . -e test -A user=$$(id -u):$$(id -g)
