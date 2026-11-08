# Nova Laser Quote v1.2.2

- Click any filename in **Batch quotation · review parts** to inspect its DXF before calculating.
- Part inspector appears inline on the same page, with geometry, bounding footprint, closed contour area, DXF drawing, open-endpoint count, and nesting readiness.
- After a successful batch calculation, the same inspector shows the part's cost breakdown.
- DXF diagnostics appear immediately below the parts table, with clickable affected filenames.
- If nesting fails, the error now includes the failing filename, rather than a generic open-contour error.
- The endpoint check is a heuristic with 0.15 mm snap tolerance, not a complete CAD repair tool.

Build through the existing GitHub Actions workflow. Preserve the existing data folder.
