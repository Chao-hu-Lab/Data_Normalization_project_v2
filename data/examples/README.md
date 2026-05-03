# Example Data

This directory is reserved for curated, non-private example workbooks that are useful for README demos, tutorials, and acceptance checks.

Current small fixtures remain in `data/`. Add larger or more narrative examples here only when they can be shared safely.

Required metadata for each future example:

| File | Provenance | Use case | Size | Notes |
| --- | --- | --- | --- | --- |
| `example-name_AfterVBA.xlsx` | Synthetic / de-identified source | GUI demo, Step 1-3 smoke, diagnostics-only Step 4 demo, or acceptance reference | To be filled | Include any expected limitations. |

Rules:

- Use the post-VBA workbook layout expected by DNP.
- Include `RawIntensity` and `SampleInfo`.
- Do not include patient identifiers, private sample names, unpublished study metadata, or absolute local paths.
- Prefer small files that are fast enough for local smoke tests.
