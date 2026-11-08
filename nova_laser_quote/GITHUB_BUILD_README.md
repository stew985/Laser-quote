# Nova Laser Quote v1.2 — GitHub standalone Windows build

This version includes the clickable part filename in the **Calculate selected parts**
results. Click a filename after calculating to view its DXF drawing, dimensions,
sheet allocation and itemized quote breakdown.

## Build on GitHub
1. Create or open your GitHub repository for Nova Laser Quote.
2. Upload the contents of this folder to the repository root, **including `.github`**.
3. Open **Actions → Build Nova Laser Quote for Windows → Run workflow**.
4. Download the `NovaLaserQuote-Windows` artifact when the workflow finishes.
5. Extract the ZIP and run `Start-Nova-Laser-Quote.bat`.

The Windows `.exe` is built by GitHub Actions; the source ZIP itself is not an executable.

## Data
Each Windows installation uses its own `data` folder next to `NovaLaserQuote.exe`.
To migrate your existing quotes and material settings, copy the old `data` folder
next to the new executable before starting it.

Do not expose port 8081 directly to the public internet. This build binds to localhost
through the included launcher.

## Note
The standalone Windows build has not been executed in this Linux environment.
