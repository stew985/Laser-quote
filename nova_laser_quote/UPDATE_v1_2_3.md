# v1.2.3: file-by-file DXF checks

- Filename buttons open an inline drawing inspector before calculation.
- Each imported DXF is checked separately for missing/unsupported geometry and open endpoints.
- Affected rows are highlighted and a diagnostics list names the problem files.
- Calculation processes only validated files; excluded files remain unpriced and the incomplete quote cannot be saved as a complete quotation.
- Inspection costs are matched by file ID, even when some DXFs are excluded.

## Important: verify the new version is running
The top-right application header must say `v1.2.3 · Click-to-inspect + file-by-file checks`.
If it doesn't, you are still running an older executable. Stop all old NovaLaserQuote processes, replace the extracted Windows build with the latest GitHub Actions artifact, and restart. Uploading source to GitHub alone does not update the executable.

This source archive is for GitHub Actions, not a ready-built EXE. Python/JS syntax and ZIP checks completed; Windows EXE runtime not verified.
