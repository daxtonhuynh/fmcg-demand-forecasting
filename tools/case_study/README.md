# Case study page

`index.html` at the repository root is the portfolio case study. This folder rebuilds it
from the pipeline outputs, so the numbers on the page always match the results.

```
tools/case_study/
├── build_case_study.py     fills index.template.html and writes the chart CSVs
├── index.template.html     page layout, styles and text, with {{placeholders}}
└── facts.json              every number used in the page text (written on each build)
```

## Rebuild the page

```bash
python uncertainty_planning/run_planning.py      # the planning outputs the page reads
python tools/case_study/build_case_study.py      # writes index.html and assets/data/*.csv
```

The builder finds the raw dataset the same way as the planning pipeline
(`data/raw/`, `uncertainty_planning/data/raw/` or `$FMCG_RAW_CSV`). The main project's
model comparison (stage 5) is typed into the builder from the README table; update it
there if stage 5 changes.

Charts are plain HTML (no chart library), so labels stay legible at every width. Static
assets are not generated: `assets/favicon.svg`, `assets/og-image.png` (1200 × 630 share
image) and `assets/img/planning-dashboard.webp` (screenshot of the planning dashboard).

A few sentences in the template describe the current results in words (for example,
which interval method under-covers). If the pipelines are re-run on different data,
read the page once and adjust those sentences in `index.template.html`.

## Publish with GitHub Pages

1. Push the repository, including `index.html`, `.nojekyll` and `assets/` at the root.
2. **Settings → Pages** → Source: *Deploy from a branch* → Branch `main`, folder `/ (root)`.
3. After a minute the site is live at `https://daxtonhuynh.github.io/fmcg-demand-forecasting/`.
   Both dashboards open from the page through relative links:
   `dashboard/index.html` and `uncertainty_planning/dashboard/index.html`.

If the repository has another name, replace `fmcg-demand-forecasting` in
`index.template.html` and the root `README.md`, then rebuild:

```bash
grep -rl "fmcg-demand-forecasting" index.html README.md tools/case_study/index.template.html
```

The share preview (`og-image.png`) appears only once the site is public.
