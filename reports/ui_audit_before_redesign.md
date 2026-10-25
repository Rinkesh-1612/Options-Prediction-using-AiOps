# UI audit of the first page (before the redesign), 2026-10-25

| Check | Result | Findings |
|---|---|---|
| no console or page errors | pass |  |
| no horizontal scroll (responsive) | pass |  |
| every control has an accessible name | pass |  |
| touch targets >= 44 px on a phone | FAIL | 13 |
| no text below 12 px | pass |  |
| text contrast >= 4.5:1 (3:1 for large text), light and dark | FAIL | 60 |
| visible keyboard focus | FAIL | 1 |
| no 'undefined' / 'NaN' / 'null' text | pass |  |
| jargon on the first screen is explained (term button) or folded away | FAIL | 4 |
| API down: readable alert + Try again button | FAIL | 2 |
| tabs exist | pass |  |

## text contrast >= 4.5:1 (3:1 for large text), light and dark
- 375px/light/signal: b.warn 3.64 "No proven edge."
- 375px/light/signal: span.num 4.40 "+₹24"
- 375px/light/signal: span.num 4.40 "+₹18"
- 375px/light/signal: span.num 4.40 "+₹14"
- 375px/light/signal: span.num 4.40 "+₹6"
- 375px/light/results: span.chip 3.78 "champion"
- 375px/light/results: b 4.02 "Direction: no edge detec"
- 375px/light/results: div#verdict.banner 4.02 "The champion (lgbm_reg, "
- 375px/light/results: b 4.02 "−₹1,376"
- 375px/light/results: span.chip 3.78 "champion"
- 375px/light/pipeline: span.warn 3.64 "*"
- 375px/light/pipeline: span.warn 3.64 "*"
- … 48 more

## touch targets >= 44 px on a phone
- 375px/light/signal: select#day 309x40
- 375px/light/signal: button.btn 68x29
- 375px/light/signal: button.btn 50x29
- 375px/light/signal: button.btn 50x29
- 375px/light/signal: button.btn 68x29
- 375px/light/signal: button#go.btn 112x40
- 375px/light/pipeline: button#pipe-refresh.btn 69x29
- 375px/light/ops: input#token 309x42
- 375px/light/ops: input#reason 309x42
- 375px/light/ops: button#rollback.btn 182x40
- 375px/light/ops: button#retrain.btn 165x40
- 375px/light/ops: a.btn 273x40
- … 1 more

## jargon on the first screen is explained (term button) or folded away
- 375px/light/signal: SHAP in "Starts from the average −₹89; each input"
- 375px/light/signal: drift in "Drift 26%"
- 1440px/light/signal: SHAP in "Starts from the average −₹89; each input"
- 1440px/light/signal: drift in "Drift 24%"

## visible keyboard focus
- no visible focus ring on BODY

## API down: readable alert + Try again button
- no visible [role=alert] when the API is unreachable
- no 'Try again' button when the API is unreachable

