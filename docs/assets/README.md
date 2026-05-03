# README Assets

This directory is reserved for small, verified media used by the repository README.

Expected assets:

| File | Purpose | Capture rule |
| --- | --- | --- |
| `dnp-gui-overview.png` | Main README GUI preview | Capture the GUI after selecting `data/feature_matrix_with_qc_AfterVBA.xlsx`, with `SpecNorm+PQN` selected and Auto Run ready. |
| `dnp-step3-session.png` | Optional session/output preview | Capture a non-private run folder showing the Step 3 workbook and generated plots. |

When `dnp-gui-overview.png` exists, embed it in the main README with:

```markdown
![DNP GUI overview](docs/assets/dnp-gui-overview.png)
```

Keep screenshots small enough for GitHub rendering. Do not include private sample names, patient identifiers, absolute local paths, or unpublished research data in README assets.
