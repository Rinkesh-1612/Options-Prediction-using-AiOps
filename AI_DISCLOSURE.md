# AI disclosure

The course code of conduct "Fair and Responsible Use of AI" requires this file.

## Tool

Claude (Anthropic), in Claude Code. It worked in this repository on my server.

## How I used it

- Claude wrote most of the code, the tests, the Docker and DVC configuration, the monitoring, the web page
  and the documents.
- Claude ran the pipeline and the checks, and reported the results.
- I set the problem: NIFTY options, intraday, after costs.
- I supplied the data: my own recordings from my trading system, Ravion V2.
- I made these decisions: NIFTY only; the cost rules (from my broker contract notes); a holding time that
  follows the market; a baseline for each model; two questions (direction and volatility); report the
  negative result.
- I reviewed each lifecycle step (`docs/steps/`) and asked for changes.

## History

| Date | Work |
|---|---|
| to 2026-10-22 | A first version. I did not review its documents, so I removed them (Git history before `817a1b1`). |
| 2026-10-23 to 10-26 | The pipeline again, one step at a time, with my review. Then the volatility model and the web page. |
| 2026-11-08 to 11-11 | A check against the course guidelines: CI in DVC, monitoring of all parts, document updates. |
| 2026-11-11 to 11-14 | I decided that the project was too large. Claude removed 6 model families, the strategy simulator and one stage. |

## Impact

The AI wrote most of the lines. It made a project of this size possible in the time I had. The problem, the
data, the design decisions and the honest report of the result are mine.

Every number comes from a recorded run (`logs/runs.jsonl`) and an MLflow run with its Git commit. No number
comes from text that the AI wrote. I am responsible for each part, and I can explain each part.
