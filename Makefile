# One entry point for every routine task. Everything runs in the pipeline image (./pipe), so results do not
# depend on the host Python. `make help` lists the targets.
.DEFAULT_GOAL := help
.PHONY: help build ci lint format test test-unit e2e ui report pipeline dag status metrics stack-up stack-down demo mlproject-test

help:            ## list the targets
	@grep -E '^[a-z0-9-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-16s %s\n", $$1, $$2}'

build:           ## build the pipeline image (Python, Java, Spark, Ray)
	./pipe build

ci:              ## CI with DVC: rerun what changed, lint + tests, then the acceptance gate (same as the pre-push hook)
	./pipe dvc repro gate

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

ui:              ## browser audit of the running page: errors, responsive, contrast, focus, jargon (needs Playwright on the host)
	UI_URL=$${UI_URL:-http://127.0.0.1:8080} /usr/bin/python3 tests/ui/ui_audit.py --md reports/ui_audit.md

report:          ## run every test and write reports/test_report.md
	./pipe python scripts/test_report.py

pipeline:        ## rerun every out-of-date DVC stage
	./pipe dvc repro

dag:             ## print the pipeline graph
	./pipe dvc dag

status:          ## which stages are out of date
	./pipe dvc status

metrics:         ## metrics and params of this commit vs the last one (dvc metrics diff / params diff)
	./pipe dvc metrics diff HEAD~1
	./pipe dvc params diff HEAD~1

stack-up:        ## build and start the serving and monitoring stack
	./stack up -d --build

stack-down:      ## stop the stack (data and volumes stay)
	./stack down

demo:            ## replay the unseen days through the API so Grafana moves (stop: ./stack stop replay)
	./stack --profile demo up -d replay

mlproject-test:  ## run the test entry point through MLflow Projects (needs mlflow on the host)
	mlflow run . -e test -A user=$$(id -u):$$(id -g)
