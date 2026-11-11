"""Draw docs/architecture.svg (runtime architecture) and docs/hld.svg (high-level design). No dependencies.

Run:  python3 scripts/make_diagrams.py
"""

from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

DOCS = Path(__file__).resolve().parents[1] / "docs"
FONT = "font-family='system-ui,-apple-system,Segoe UI,Roboto,sans-serif'"
COLORS = {
    "data": ("#e8f0fe", "#4c72b0"),
    "pipe": ("#e6f4ea", "#2e7d4f"),
    "model": ("#fff4e0", "#c77700"),
    "serve": ("#f3e8fd", "#7b3fb3"),
    "ops": ("#fde8e8", "#c0392b"),
    "note": ("#f5f6f8", "#9aa3af"),
}


class Svg:
    def __init__(self, w: int, h: int, title: str):
        self.w, self.h, self.parts = w, h, []
        self.parts.append(f"<rect width='{w}' height='{h}' fill='white'/>")
        self.text(24, 34, title, 20, weight=700)

    def text(self, x, y, t, size=13, weight=400, fill="#14171c", anchor="start"):
        lines = t.split("\n")
        for i, line in enumerate(lines):
            self.parts.append(
                f"<text x='{x}' y='{y + i * (size + 3)}' font-size='{size}' font-weight='{weight}' fill='{fill}' "
                f"text-anchor='{anchor}' {FONT}>{escape(line)}</text>"
            )

    def panel(self, x, y, w, h, title, kind="note"):
        fill, stroke = COLORS[kind]
        self.parts.append(
            f"<rect x='{x}' y='{y}' width='{w}' height='{h}' rx='12' fill='{fill}' fill-opacity='.45' "
            f"stroke='{stroke}' stroke-dasharray='5 4'/>"
        )
        self.text(x + 12, y + 22, title, 13, 700, stroke)

    def box(self, x, y, w, h, t, kind="pipe", size=12):
        fill, stroke = COLORS[kind]
        self.parts.append(
            f"<rect x='{x}' y='{y}' width='{w}' height='{h}' rx='8' fill='{fill}' stroke='{stroke}' stroke-width='1.6'/>"
        )
        lines = t.split("\n")
        y0 = y + h / 2 - (len(lines) - 1) * (size + 3) / 2 + size * 0.35
        for i, line in enumerate(lines):
            self.text(x + w / 2, y0 + i * (size + 3), line, size, 700 if i == 0 else 400, anchor="middle")

    def arrow(self, pts, label="", dash=False, lx=None, ly=None):
        d = "M" + " L".join(f"{x},{y}" for x, y in pts)
        dashed = " stroke-dasharray='5 4'" if dash else ""
        self.parts.append(
            f"<path d='{d}' fill='none' stroke='#5d6673' stroke-width='1.6' marker-end='url(#a)'{dashed}/>"
        )
        if label:
            (x1, y1), (x2, y2) = pts[0], pts[-1]
            self.text(
                lx if lx is not None else (x1 + x2) / 2,
                ly if ly is not None else (y1 + y2) / 2 - 6,
                label,
                11,
                fill="#3d4651",
                anchor="middle",
            )

    def save(self, name: str):
        marker = (
            "<defs><marker id='a' viewBox='0 0 10 10' refX='9' refY='5' markerWidth='7' markerHeight='7' "
            "orient='auto-start-reverse'><path d='M0,0 L10,5 L0,10 z' fill='#5d6673'/></marker></defs>"
        )
        body = "\n".join(self.parts)
        (DOCS / name).write_text(
            f"<svg xmlns='http://www.w3.org/2000/svg' width='{self.w}' height='{self.h}' viewBox='0 0 {self.w} {self.h}'>"
            f"{marker}\n{body}\n</svg>\n"
        )


def architecture() -> None:
    s = Svg(1300, 700, "Architecture: one VPS, Docker, no cloud")
    s.panel(20, 60, 230, 440, "Data source", "data")
    s.box(40, 100, 190, 60, "Upstox\nmarket feed", "data")
    s.box(40, 200, 190, 60, "Ravion V2\nrecorder (live system)", "data")
    s.box(40, 300, 190, 60, "ClickHouse\nread-only access", "data")
    s.arrow([(135, 160), (135, 200)])
    s.arrow([(135, 260), (135, 300)])
    s.text(
        40,
        400,
        "Stage export copies it once\ninto a frozen Parquet snapshot\n(row counts verified).",
        11,
        fill="#3d4651",
    )

    s.panel(290, 60, 480, 440, "Pipeline: DVC stages in the pipeline image (./pipe)", "pipe")
    row1 = [("export", 300), ("check\nSpark", 408), ("clean\nRay", 516), ("grid\nRay", 624)]
    for t, x in row1:
        s.box(x, 100, 100, 56, t, "pipe")
    for (_, x1), (_, x2) in zip(row1, row1[1:], strict=False):
        s.arrow([(x1 + 100, 128), (x2, 128)])
    row2 = [("feat\nRay", 300), ("labels\nRay", 408), ("vol\nHAR vs IV", 516), ("drift\nPSI", 624)]
    for t, x in row2:
        s.box(x, 200, 100, 56, t, "pipe")
    s.arrow([(674, 156), (674, 178), (350, 178), (350, 200)], "data/grid", lx=520, ly=172)
    s.box(300, 300, 190, 56, "zoo_train\nRay Tune, walk-forward CV", "model")
    s.box(515, 300, 205, 56, "zoo_eval\ntest days once + deploy gate", "model")
    s.arrow([(490, 328), (515, 328)])
    s.arrow([(350, 256), (350, 300)], "data/feat + labels", lx=440, ly=282)
    s.box(
        300,
        392,
        420,
        90,
        "Version control and CI/CD\nGit: code, configs, reports, run journal   Git LFS: sample day\nDVC: data + dvc.yaml DAG;  `dvc repro` = train, evaluate, deploy\nCI: dvc repro gate (tests -> gate), run by pre-push",
        "note",
        11,
    )
    s.arrow([(230, 330), (270, 330), (270, 128), (300, 128)])

    s.panel(810, 60, 470, 590, "Docker Compose stack (./stack)", "serve")
    s.box(830, 100, 200, 66, "frontend  :8080\nnginx, static page, config.json", "serve")
    s.box(1060, 100, 200, 66, "api  :8000\nFastAPI (the only public entry)", "serve")
    s.arrow([(1030, 133), (1060, 133)], "REST", ly=124)
    s.box(830, 200, 200, 66, "mlflow  :5050\ntracking + model registry", "model")
    s.box(1060, 200, 200, 66, "model  :5001\nmlflow models serve (champion)", "serve")
    s.arrow([(1160, 166), (1160, 200)], "/invocations", lx=1200, ly=186)
    s.arrow([(1030, 233), (1060, 233)], "alias", ly=224)
    s.arrow([(770, 233), (830, 233)], "runs", lx=800, ly=224)
    s.box(830, 300, 200, 66, "runner\nretrain: alert, button, schedule", "ops")
    s.box(1060, 300, 200, 66, "prometheus  :9091\nscrapes every 5 s", "ops")
    s.arrow([(830, 333), (770, 333)], "dvc repro", lx=800, ly=324)
    s.box(830, 400, 200, 66, "alertmanager\nDriftDetected, ModelLosing", "ops")
    s.box(1060, 400, 200, 66, "grafana  :3001\nnear-real-time dashboard", "ops")
    s.arrow([(1160, 366), (1160, 400)])
    s.arrow([(1060, 433), (1030, 433)], "alerts", ly=424)
    s.arrow(
        [(930, 466), (930, 492), (1272, 492), (1272, 133), (1260, 133)],
        "webhook: retrain request",
        dash=True,
        lx=1100,
        ly=486,
    )
    s.box(830, 520, 200, 66, "node-exporter\nhost CPU, memory, disk", "ops")
    s.text(
        1050,
        540,
        "Prometheus also scrapes the api\n(signals, drift, pipeline, quality)\nand mlflow.",
        11,
        fill="#3d4651",
    )

    s.box(
        290,
        520,
        480,
        60,
        "Security: AES-256 encrypted backup of data + models\n(scripts/encrypt_snapshot.sh); admin token; localhost only",
        "note",
        11,
    )
    s.save("architecture.svg")


def hld() -> None:
    s = Svg(1210, 740, "High-level design: from raw ticks to a served, monitored forecast")
    lanes = [
        (60, "1  Data", "data", 90),
        (180, "2  Features and targets", "pipe", 90),
        (300, "3  Models", "model", 90),
        (420, "4  Release", "serve", 90),
        (540, "5  Operate", "ops", 170),
    ]
    for y, name, kind, h in lanes:
        s.panel(20, y, 830, h, name, kind)

    def row(y, items, kind, w=190):
        x = 40
        for t in items:
            s.box(x, y, w, 52, t, kind, 11)
            x += w + 20
        return [40 + i * (w + 20) for i in range(len(items))]

    xs = row(
        92,
        [
            "raw ticks\nClickHouse -> Parquet",
            "check\naccept or reject each day",
            "clean\noutlier rules, fill with age limit",
            "grid\n1 row per second, ATM +-2 legs",
        ],
        "data",
        190,
    )
    for a, b in zip(xs, xs[1:], strict=False):
        s.arrow([(a + 190, 118), (b, 118)])
    row(
        212,
        [
            "feature library\n46 features, tested for look-ahead",
            "triple-barrier labels\nnet rupees of a trade",
            "volatility targets\nrealized move, 5 and 15 min",
        ],
        "pipe",
        250,
    )
    row(
        332,
        [
            "model zoo: 9 families\nwalk-forward CV, Ray Tune",
            "volatility forecaster\nHAR vs the option market's IV",
        ],
        "model",
        250,
    )
    xs = row(
        452,
        [
            "test days scored once\nchoose on validation only",
            "deploy gate\nsmoke test before serving",
            "model registry\nchampion / previous",
            "model server + API\nrollback if a version fails",
        ],
        "serve",
        190,
    )
    for a, b in zip(xs, xs[1:], strict=False):
        s.arrow([(a + 190, 478), (b, 478)])
    row(
        572,
        [
            "web page\nforecast, does it work, how built, controls",
            "Prometheus + Grafana\nmetrics, alerts, drift",
        ],
        "ops",
        250,
    )
    row(
        642,
        ["drift check (PSI)\nper day and online", "retrain: alert, button, schedule\nthen the gate again"],
        "ops",
        250,
    )
    for y1, y2 in ((150, 180), (270, 300), (390, 420), (510, 540)):
        s.arrow([(435, y1), (435, y2)])
    s.arrow([(560, 668), (885, 668), (885, 358), (580, 358)], "retrain", dash=True, lx=905, ly=520)

    s.panel(930, 60, 260, 650, "Design rules", "note")
    rules = [
        "1  No look-ahead.\nEvery input uses data up to its\nsecond. Gaps: forward fill\nwith an age limit.",
        "2  One definition of a trade.\nBuy at the ask, sell at the bid,\nstatutory costs. Labels,\nsimulator and API share it.",
        "3  The day is the unit.\nStages run per day (Ray).\nSplits are by whole day.",
        "4  Choose on validation,\nreport on test.\nTest days are scored once.",
        "5  Everything is a stage.\nDVC runs it; the run journal and\nMLflow record the commit.",
        "6  Loose coupling.\nThe page knows only the API\naddress (config.json).\nFunctional stages: files in,\nfiles out.",
    ]
    for i, r in enumerate(rules):
        s.text(946, 106 + i * 98, r, 12)
    s.save("hld.svg")


if __name__ == "__main__":
    architecture()
    hld()
    print("wrote docs/architecture.svg and docs/hld.svg")
