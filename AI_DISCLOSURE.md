# AI Disclosure

Required by the course "Fair and Responsible Use of AI" code of conduct.

**Tool:** Claude (Anthropic), through Claude Code, working in this repository on the author's VPS.

**What the author decided:** the problem (NIFTY intraday options, after costs), the data (the author's own
recordings from Ravion V2), NIFTY-only scope, the cost rules (from the author's broker contract notes), a
holding time set by the market instead of a fixed horizon, a comparison of model families against a baseline instead of one model,
reuse of the old test days, and the review of every rubric item (`docs/steps/`).

**What Claude did:** wrote most of the code, tests, Docker and DVC configuration, monitoring, the web page
and these documents; ran the pipeline and the checks; and reported the results, including the negative ones.

**History:**
- Until 2026-10-22: a first version (minute and second-level models) was built with Claude. The author did
  not review its documents. On 2026-10-23 the author marked them deprecated and they were removed
  (still in Git history before commit `817a1b1`).
- 2026-10-23 to 10-24: the pipeline was rebuilt item by item with the author's review: cleaning, 1-second grid,
  feature library, triple-barrier labels, direction models, deploy gate, drift, monitoring, web page, documents.
- 2026-10-24 to 10-26: with Claude: the volatility forecaster, the Explore page, and research studies on branches.
- 2026-11-08 to 11-11: the author asked Claude to check the project against the official evaluation guideline and
  to finish it. Claude moved CI into the DVC pipeline (stages `tests` and `gate`, as in course lecture 11), fixed a
  page error, added monitoring of every component, removed unused files and brought the documents up to date.
- 2026-11-11: after a review of the demo, the author decided the project was too large for a course assignment.
  Claude removed 6 of 9 direction model families (deep models included), 1 of 4 volatility models, the option
  strategy simulator and one pipeline stage. They are in Git history before this date.

**Impact:** AI wrote most of the lines in this repository. It made the breadth possible (a 13-stage pipeline, tests,
monitoring, a web page) in the time available. The problem, the data, the design choices listed above and
the decision to report the negative trading result are the author's.

**Where the numbers come from:** every result comes from a journaled run (`logs/runs.jsonl`, `logs/`) and an
MLflow run tied to a Git commit and DVC data hashes, never from text written by AI. The author is responsible
for, and can explain, every component.
