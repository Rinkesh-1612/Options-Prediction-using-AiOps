# AI Disclosure

Required by the course "Fair and Responsible Use of AI" code of conduct.

**Tools used:** Claude (Anthropic), via Claude Code, running against this repository.

**How it was used:**
- Pair-programming: drafting the pipeline code (export, Spark check/bars, run journal), Dockerfiles, DVC stages and tests, which were then run on the VPS by the author.
- Debugging: pasting real error output (Docker/Java version, Spark container errors) to find root causes.
- Brainstorming the project plan; the author chose the problem, the data, the NIFTY-only scope, the trading cost rules (taken from the author's own Ravion trading system) and approved each design decision.

**Impact:** AI sped up boilerplate and debugging. All data comes from the author's own recorded market data; all results in the report come from journaled pipeline runs (`runs/runs.jsonl`, `logs/`), not from AI-generated numbers. The author is responsible for, and must be able to explain, every component (design choices: docs/HLD.md section 3).

**Update, 2026-10-19:** Claude Code also wrote the monitoring stack (Prometheus, Alertmanager, Grafana
dashboard), the drift check, the replay tool, the Ray Tune stage, `MLproject`, the pre-push hook, the
encryption script, extra tests, and the documents in `docs/`. The author ran the system and must
explain each part. The documents follow simplified technical English, as the author asked.

**Update, 2026-10-22:** Claude Code (Claude Opus 5.5) reviewed the repository against the course guidelines, then:
moved planning notes and side research out of the submission (the research is kept on branch `alpha-lab`),
wrote the final test protocol, the `register` and `evaluate` stages and their tests, the `/results` endpoint and the
Results tab, `docs/RESULTS.md`, and updated the other documents. The author decided to open the locked test days,
to drop BANKNIFTY and to archive the side research. Every number in `docs/RESULTS.md` comes from the journaled
run `20261022T161450-evaluate` (`reports/final.json`).
