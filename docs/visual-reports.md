# Visual benchmark reports

Every benchmark export now includes a self-contained `report.html`. It uses
inline CSS and SVG, makes no network requests, and can be opened directly after
the campaign finishes.

## Included views

- **Algorithm ranking** uses horizontal bars for mean normalized value ratio;
  the exact aggregate table remains available below the chart.
- **Difficulty heatmap** compares every configured solver across all configured
  synthetic difficulty tiers on the same normalized scale.
- **Search convergence** plots all iterative solvers for one scenario and seed.
  Incumbent points are not presented as independent samples.
- **Representative schedule** shows observation and slew intervals on one time
  axis for a replayed solver run.

The default representative run uses the last scenario in matrix order, the
rank-one solver, and the first configured algorithm seed. Choosing the final
matrix cell usually makes the default schedule one of the larger, harder
instances.

## Custom selection

Render another scenario, solver, or seed from an existing JSON report:

```bash
orbitops report runs/benchmark-smoke/report.json \
  --output runs/medium-hard-genetic.html \
  --scenario-id benchmark-smoke-medium-hard-000 \
  --solver genetic \
  --seed 1
```

All selections must already belong to the benchmark specification. The renderer
regenerates the selected scenario from its committed generator inputs, checks
its content hash, reruns the selected solver with the original budget, and
compares the resulting metrics with the stored run. The HTML reports whether
that representative replay matched.

## Accessibility and responsive behavior

Charts have accessible names and descriptions, values are directly labeled,
and color is paired with solver names or interval types. At narrow screen widths,
the two dense SVG plots are replaced by semantic data tables so chart text does
not become unreadably small. Light and dark themes follow the operating-system
preference.

## Interpretation boundary

The visual report presents the campaign data; it does not strengthen the
underlying evidence. A high bar or dark heatmap cell means better performance
within the configured synthetic benchmark only. Runtime remains descriptive and
machine-dependent, and the replay indicator verifies metrics rather than
proving optimality.
