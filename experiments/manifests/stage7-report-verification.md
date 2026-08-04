# Stage 7 visual-report verification

## Material Passport

- Origin Skill: visualize
- Origin Mode: build / structural validation
- Origin Date: 2026-08-04
- Verification Status: VERIFIED (structural)
- Version Label: stage7-report-v1

## Verification Result

- Input campaign: `configs/benchmark-smoke.toml`
- Command: `.venv/bin/orbitops benchmark configs/benchmark-smoke.toml --output runs/stage7-smoke`
- Generated visual artifact: `runs/stage7-smoke/report.html`
- Custom-selection command: `.venv/bin/orbitops report runs/stage7-smoke/report.json --output runs/stage7-custom.html --scenario-id benchmark-smoke-tiny-hard-000 --solver local-search --seed 1`
- Automatic report selection: `benchmark-smoke-medium-hard-000`, `genetic`, seed `0`
- Custom report replay verification: passed
- External scripts, fonts, images, or data requests: none
- Responsive fallback: semantic tables below 640 CSS pixels
- Integrity coverage: `report.html` included in `manifest.json`
- Quality suite: 89 tests passed; 91.34% branch-aware coverage

Automated checks assert all four required views, accessible chart roles, mobile
fallback tables, dark-theme rules, representative metric replay, and absence of
scripts or external URLs. Browser automation could not open the local file under
the active URL security policy, so this record verifies structure and generated
content rather than claiming screenshot-based visual approval.
