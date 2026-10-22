# User manual

For a trader. No programming knowledge is needed.

## What this tool does

You pick a past minute of a trading day. The tool shows what the model would have told you at that minute.
It then shows what really happened in the next 2 minutes.

The model gives one of three answers:

| Answer | Colour | Meaning |
|---|---|---|
| **Buy the call (CE)** | green | The model thinks the call will pay more than the costs. |
| **Buy the put (PE)** | red | The model thinks the put will pay more than the costs. |
| **Stay out** | grey | The model does not see a trade worth the costs. |

"Costs" means the gap between buy and sell price, taxes and slippage.
A trade must beat all of them to count as a win.

> **Read this first.** The tool is a research aid. It does not trade for you.
> At the time of writing, on the validation days, no simple rule made money after costs.
> The trained model therefore says "Stay out" on every minute. This is a real result, not a fault.

## Open the page

1. Open `http://127.0.0.1:8080` in a browser on the server.
2. From another computer, first create a tunnel:
   `ssh -L 8080:127.0.0.1:8080 -L 8000:127.0.0.1:8000 -L 5050:127.0.0.1:5050 -L 3001:127.0.0.1:3001 trader@<server>`
   Then open `http://127.0.0.1:8080`.
3. Look at the dot under the title. **Green** means the model is ready. **Red** means it is not. Wait one minute and refresh.

## Tab 1: Pick a minute

1. Choose a **Day**. The list shows only days the tool may show.
2. Move the **time slider**, or tap ◀ and ▶ to move one minute.
3. Read the result card:
   * The large text is the answer.
   * The sentence under it says why, in plain words.
   * "How sure is the model" shows bars for how likely each answer is.
   * "What pushed the model" lists the three inputs that mattered most.
   * "What actually happened" shows the result in rupees after costs for the call and for the put,
     and which one was best in hindsight.

**Yellow warning "The model was trained on this day".** The model has seen this day.
A good result here proves nothing. Choose a validation day to judge the model.

## Tab 2: Pipeline

This tab shows how the model was built.

* **Boxes at the top.** Each box is a step. Green = the last run worked. Red = it failed. Grey = no run yet.
* **Model.** Shows the live model and the previous one.
  * **Retrain now** asks the system to train a new model. The new model replaces the old one only if it does better on validation.
  * **Roll back to previous model** puts the older model back at once. Use it if the new model behaves badly.
  * Both buttons ask for confirmation. They need the admin token (see below).
* **Runs.** Every run of every step. Tap a row to read its log. A red row means an error; the log says why.
* **Tools.** Links to MLflow (all experiments) and Grafana (live monitoring).

### The admin token

The two buttons change what the system serves, so they need a token.
The first time you press one, the page asks for it. The token is `ADMIN_TOKEN` in the `.env` file on the server.

## Live monitoring (Grafana)

Open `http://127.0.0.1:3001`. The dashboard refreshes every 5 seconds. It has four rows:

1. **The problem.** What the model chose, prediction against what happened, hit rate, and result in rupees.
2. **Health.** Is each part up? How fast does the system answer?
3. **Drift.** Does today's market look like the data the model learned from? Bars turn yellow at 0.10 and red at 0.25.
4. **Pipeline and server.** Did the last run of each step work? How busy is the server?

To see the dashboard move without waiting for the market, start the demo feed:
`./stack --profile demo up -d replay`. It replays the six validation days in a loop. Stop it with `./stack stop replay`.

## When something goes wrong

| What you see | What it means | What to do |
|---|---|---|
| Red banner "Cannot reach the backend" | The API is down or the address is wrong. | Run `./stack ps`. Run `./stack up -d`. |
| Red dot, "model not ready" | The model server is still starting. | Wait one minute. Then refresh. |
| "Day not available" | The day is a locked test day or has no data. | Choose another day. |
| 401 after a button press | Wrong admin token. | Check `.env`. |
| "there is no previous model" | Only one model exists. | Nothing to roll back to. |
| Red box in the Pipeline tab | A step failed. | Tap its run. Read the log. |

## Words used

| Word | Meaning |
|---|---|
| Call (CE), Put (PE) | The two kinds of option. A call gains when the index rises. A put gains when it falls. |
| Spread | The gap between the buy price (ask) and the sell price (bid). You pay it on every trade. |
| Slippage | The price moves a little against you while the order fills. |
| Validation day | A day used to choose the settings. Not used to teach the model. |
| Test day | A day kept locked until the end. It gives the one honest score. |
| Drift | The market has changed from what the model learned. |
| Champion | The model that is live now. |

## Show the drift and retrain chain (demo)

Real drift needs several days of data. To show the chain in a few minutes, lower the limits:

```bash
DRIFT_PSI_LIMIT=0.02 DRIFT_MIN_ROWS=100 ./stack up -d api
DRIFT_PSI_LIMIT=0.02 DRIFT_MIN_ROWS=100 ./stack --profile demo up -d replay
```

Watch Grafana. The "Drift detected" tile turns red. Prometheus fires `DriftDetected` after 30 seconds.
Alertmanager calls the API. The API writes a retrain request. The runner trains a new model.
The Pipeline tab shows the new run. The new model replaces the champion only if it validates better.
Then restore the real limits: `./stack up -d api`.
