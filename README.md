# Nova Laser Quote v0.4 — shop-network batch quoting

## Install on Windows
1. Extract the ZIP to a NEW folder.
2. Stop the previous Nova server if it uses port 8081.
3. Copy the existing `data` folder from the previous version into this new `nova_laser_quote` folder to preserve quote history, material settings, and uploaded DXFs.
4. Double-click `start_windows.bat`. Leave the black terminal open.
5. Open **http://localhost:8081** on the host computer. On other shop computers, use `http://HOST-LAN-IP:8081` and allow inbound TCP 8081 on Windows Firewall only for the private shop network.

## Batch quoting workflow
1. Drop a folder, ZIP, or RFQ email containing DXFs into the RFQ inbox.
2. Tick the DXFs to quote (or click Check all).
3. Click **Calculate selected parts** below the drawing list.
4. Review the table, correct material, thickness and quantity for every line.
5. Click **Calculate selected parts** in the review table to see prices.
6. Click **Save batch & generate PDF** to create a combined quote. Find saved quotes in Quote history.

## Pricing model and limitations
- Material usage is based on the bounding rectangle and a utilization assumption, **not optimized nesting**.
- Cut length and pierce counts are geometry-based estimates, not CAM toolpath simulations.
- Filename hints recognize examples such as `0.125 ALUMINUM - QTY 2` and `0.500 STEEL - QTY 1`. Verify all values.
- The 3.175 mm (1/8 inch) cutting profile is seeded from 3 mm profile data and **must be calibrated** against actual Bodor cutting times. Other thicknesses without profiles must be added to Rates & materials.
- The first batch calculates one setup charge and one order minimum. Line selling prices allocate the full order total proportionally; unit prices in the PDF are displayed to four decimal places.
- Price and speed settings are illustrative, not validated. Taxes, shipping, finishing and special tolerances are excluded.
- Local shop-network only. There is **no user authentication or HTTPS**; do not expose port 8081 to the public internet.
- The import accepts up to 100 top-level files; ZIP entries are capped. DXF files are stored under `data/uploads`.

## Troubleshooting
- If browser says `This site can't be reached`, verify the black server window stays open and try `http://127.0.0.1:8081`.
- If browser says `Failed to fetch`, check the terminal for Python errors and reload with Ctrl+Shift+R.
- If prices are missing, verify all material/thickness profiles exist under Rates & materials.

## Validation
Python syntax and JavaScript syntax were checked; geometry and batch pricing were exercised with a synthetic DXF. Full Flask/Windows end-to-end testing was unavailable in the build environment.
