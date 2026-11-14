# Design direction of the web page

This file states the visual direction of `frontend/index.html` and one reason for each choice.
The page is checked against it by the browser audit (`make ui`, `reports/ui_audit.md`).

**Design read.** A research dashboard for one reader who is not a programmer (the examiner, or a trader),
in a plain Swiss-style language. Dial: ENERGY 1 / RHYTHM 2 / MOTION 1.

| Choice | What | Reason |
|---|---|---|
| Energy 1 | Calm page, no hero, no decoration | The reader comes to read numbers. Decoration competes with the charts. |
| Rhythm 2 | Numbered steps of different shape: calendar, chart, three value boxes, answer card, verdict cards | Each step shows a different kind of data, so each has its own form. The numbers keep the order clear. |
| Motion 1 | Only a loading pulse and a 1 px press on buttons; both stop under "reduce motion" | Motion shows state (loading, pressed). Nothing moves for effect. |
| Palette | Slate neutrals and one blue (`--primary`) for controls and links | One accent marks what the reader can press. |
| Meaning colours | Green, red and amber only for good, bad and warning, always with a word or an icon | The verdict must not depend on colour alone. |
| Chart colours | Three fixed colours and three line styles: our forecast (solid), options market (dashed), what happened (dotted) | The same three series appear in every chart, so the reader learns them once. Line style keeps them apart without colour. |
| Typeface | The system font; a monospace font only for times, commit IDs and logs | No font is downloaded (the server is private), and the page looks native on each device. Monospace keeps digits aligned. |
| Radius | 8 to 10 px on cards and controls; a full pill only on status tags | One shape for containers, one for status. |
| Shadow | None on cards (borders separate the surfaces). One shadow, on the explanation pop-up | The pop-up is the only element that sits above the page, so it is the only one with elevation. |
| Theme | Light and dark, following the device setting | The reader keeps the setting of the device. Both themes pass the contrast check. |
| Layout | One column, at most 1100 px wide; tabs move to the bottom on a phone | The story reads top to bottom. On a phone the tabs sit under the thumb. |
| Focal point | Per step, one large value or one sentence in plain words | The reader gets the answer before the detail. |
| Identity | The star for an unseen day, and the three line styles | The page is about a fair test, so the mark of an unseen day is on the calendar, the charts and the tables. |
| Words | Plain English, with a tap-to-explain button on each term | The reader is not a quant. |

**Not on the page, on purpose:** testimonials, usage statistics, marketing claims. Every number comes from a
report file written by the pipeline.
