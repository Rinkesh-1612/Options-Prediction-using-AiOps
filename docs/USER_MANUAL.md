# User manual

For a trader. No programming is needed to use the page. The sections "Controls" and "For the operator" are for the person who runs the server.

Open **http://&lt;server&gt;:8080** (on this server: http://<server-ip>:8080).

## What this page does, in one minute

It replays real NIFTY market days and answers two questions at any moment of the trading day:

1. **How much will NIFTY move in the next 5 or 15 minutes?** Our forecast beat the options market's own guess on every
   one of 10 days that the model had never seen. This part works.
2. **Should I buy a call or a put?** The model that tries to answer this lost money after costs on days it had never
   seen. The page shows it so that you can see how it decides, and it says clearly that it is **not proven**.

The page is **not** investment advice. It is a research system built on recorded market data.

## The screen

At the top: the name, a **status light** (green = everything normal; press it for details), a **Help** button (always
in the same place) and three tabs: **Explore**, **How it's built**, **Controls**. On a phone the tabs are at the bottom
of the screen, where your thumb is. The dark version follows your device setting.

<img src="img/phone.png" alt="The page on a phone" width="260"> <img src="img/phone-dark.png" alt="Dark mode on a phone" width="260">

## Explore: six steps, top to bottom

![Explore tab](img/explore.png)

On the first visit a short **guided tour** opens (close it any time; reopen it with **Show the guided tour**). The
buttons under the title jump to each step.

1. **Pick a day** in the calendar. ★ = unseen day (a fair test); E = expiry day; ! = big move; ~ = market-change alarm;
   a dashed day has no data.
2. **Implied volatility** (IV), four views: IV over the days, IV against our forecast and what happened, the smile (IV by
   strike) and the term structure (IV by expiry). Click a dot to pick that day.
3. **Inside one day**: IV, our forecast and what happened, one point per minute, with the NIFTY index below. Click the
   chart or drag the slider to pick a time; **−5 min / +5 min** step through time. Three boxes and one sentence say who
   was closer at that time.
4. **Strategies at that moment**: 18 ready-made strategies priced at the chosen time, after all charges: cost to open,
   result after 5, 15, 30 and 60 minutes, best exit in hindsight, best profit and worst loss at expiry. Switch to **Close
   by the barrier rule** for a take-profit / stop-loss exit. Click a row for the result by closing time and the payoff
   diagram. **Build your own** prices any 1–4 leg strategy, also unbalanced ones (for example buy 1, sell 2).
5. **What each model said** at the chosen time: the volatility forecasts against what happened, and each call/put model's
   answer with the money it would have made. A badge says whether the day is a fair test for that model. A chart shows
   the result of each model over the whole day.
6. **Verdict** in plain words: the forecast of how much NIFTY moves works; call/put prediction shows no edge after costs.
   The buttons **Does it work?** and **Forecast** open the two older, more detailed pages (below).

Every chart is interactive: point at it (or press and hold on a phone) to read the values, drag to zoom, double-click to
zoom out, click a legend name to hide a line. **Table view of this chart** shows the same numbers as a table.

## The two older pages (from step 6)

**Forecast** — one moment in detail: pick a day and time, read one sentence (for example *"NIFTY is expected to move
about 30 points over the next 15 minutes. The options market is pricing in about 74 points."*), and the call/put model's
answer. Open **"Why did it say that, and what happened next?"** for the five inputs that pushed the answer most and what
the trade would really have made. The model is marked **not proven**.

![Forecast page](img/forecast.png)

**Does it work?** — two verdict cards, the three rules of the test, and folded sections with all the numbers (the
forecasters, the call/put models with their 95% intervals, market change, what the call/put model looks at).

![Does it work page](img/works.png)

## Words you may not know

Any word with a dotted underline is a button: press it and a short explanation appears. The **Help** button shows
all of them in one list, with a short guide to the page.

![Help](img/help.png)

## How it's built

![How it's built tab](img/pipeline.png)

The factory behind the forecast. Each box is a step that turns raw data into a model. A green border means its last run
succeeded; red means it failed. Press a box to filter the runs; press a run to read its log. Below: the speed of each
step in rows per second, and the data quality (days that were rejected and why, rows that cleaning removed).
**Recent runs** starts with a count (for example "47 runs: 41 succeeded, 6 failed"); **Failed only** lists only the
failures, and a click on a run shows its log with the error.

## Controls (for the operator)

![Controls tab](img/controls.png)

- **Is everything healthy?** A list with a green tick, an amber warning or a red cross for each part.
- **Models in use.** The current call/put model and the previous one (the way back), each with its safety check.
- **Actions.** *Go back to the previous model*, *Retrain the models* and *Run the pipeline* (reruns only the steps
  whose code, data or settings changed, then all tests and the final check). Each asks you to confirm and needs the
  admin token (field above the buttons). Follow a run in **How it's built**.
- **Other tools.** Links to MLflow (experiments and models) and Grafana (live monitoring).

![Grafana dashboard](img/grafana.png)

![MLflow runs](img/mlflow-runs.png)

![MLflow registry: safety checks and aliases](img/mlflow-registry.png)

## Using the keyboard

`Tab` moves between controls and shows a blue outline on the current one. The arrow keys change the time slider and move
between the three tabs. `Esc` closes the Help window and any explanation. A link at the very top ("Skip to content")
appears on the first `Tab`.

## When something goes wrong

The page never shows a raw error. A red box says what happened in plain words and has a **Try again** button.

| Message | Meaning | What to do |
|---|---|---|
| We can't reach the forecast service | the server or the API container is stopped | `./stack up -d api` on the server |
| The model is starting up or not available yet | the model server is starting or down | wait one minute; `./stack logs model` |
| data for … is not available now | the pipeline is rebuilding the data | wait for `dvc repro` to finish |
| admin token missing or wrong | going back or retraining needs the token | enter the token on the Controls tab |
| there is no previous model to roll back to | nothing to go back to | nothing to do |

## For the operator: start, stop, update

```bash
./stack up -d --build          # start everything (page 8080, API 8000, MLflow 5050, Grafana 3001)
./stack ps                     # state of each service
./stack down                   # stop (data stays)
./pipe dvc repro               # run the pipeline; a new model is served only if it passes the safety check
make e2e                       # check the running stack
make ui                        # browser audit of this page (errors, phone width, contrast, keyboard)
bash scripts/encrypt_snapshot.sh            # encrypted backup of data and models
```
Settings are in `params.yaml`. The admin token is the environment variable `ADMIN_TOKEN` (empty = no token).
