# Vendored libraries

| File | What | Version | Licence | Source | SHA-256 |
|---|---|---|---|---|---|
| `plotly-basic.min.js` | Plotly.js, basic bundle (scatter, bar, pie; hover, zoom, legend) | 2.35.2 | MIT (`plotly.LICENSE`) | npm `plotly.js-basic-dist-min@2.35.2` | `138c2e81014b979dc00867a93da55b7605a17495ee78dd7afb433b7f021dfcfa` |

Why vendored: the page loads no code from a third-party server at run time (the server is private; no CDN, no tracking).
How it was checked: the tarball from `registry.npmjs.org` was verified against the `dist.integrity` (sha512) that the registry
publishes, then the file was extracted unchanged.
To update: download the new tarball, verify its integrity the same way, replace the file, update this table.
