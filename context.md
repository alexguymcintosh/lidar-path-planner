# context.md

A verbose, mostly-chronological record of how this project actually got
built. Includes every pivot, gotcha, half-built dead end, tool decision,
URL we needed, and decision rationale. Written so that a new collaborator
(or a future Claude session) can pick up where we left off without losing
the *why*.

This is intentionally messy and long. It's the audit log, not the polished
story — for that, see `README.md`.

---

## 1. Goal

Final-year robotics capstone. Demo target: a tractor-scale rover navigating
a real outdoor site autonomously using a lidar-derived map. Project partner
is **Anton**, who will capture his own UAV-lidar later — until then we work
against the closest public proxy we can find.

Original demo concept: drive the rover in Gazebo via teleop over a heightmap
of the lidar.

**This pivoted.** After looking at the L3 cloud in CloudCompare the user
noticed visible vehicle tracks and decided the more interesting capstone
story is: *click two waypoints, watch a planner work out a route that
prefers existing tracks over straight-line cuts across paddock*. Gazebo and
rover physics were dropped entirely from v1 scope.

The pipeline that survived the pivot:

```
LAZ point cloud → multi-layer cost raster → A* → clickable UI
```

No rover, no ROS2 stack, no Nav2 runtime — yet. Those can be layered on
later if the cost-raster recipe proves out.

---

## 2. Environment

- Workstation, local Linux (Ubuntu 24.04 Noble).
- Display server: X11 on `:1`.
- 31 GiB RAM, plenty of disk.
- Working dir: `/home/knucky-rover-team/map/`.

Tooling preferred: standard Linux, package-manageable, no Docker/sandbox.
The reason: a prior session had been in a Docker container with no display
and we restarted fresh on the host to get GUI tools working.

---

## 3. Dataset acquisition (L3 Rolling Hills)

**Source:** ROCK Robotic "Rolling Hills" public sample, captured with a
DJI Zenmuse L3.

**Spec:**
- ~164M points, 335 pts/m² density
- 658 × 747 m extent, EPSG:32736 (WGS84 UTM zone 36S, southern Africa)
- Z range 95–193 m
- 7 returns/pulse, RGB-colourised, classified (ground/unclassified)
- 1.28 GB compressed LAZ
- Share page: <https://cloud.rockrobotic.com/share/40e5e607-21cb-441f-85cf-d1eb882bd0e3>

**Gotcha (kept for reference — see also memory note `reference_rock_share_caching`):**
The share page renders a presigned AWS S3 URL directly into the `<a href>`
server-side. That URL has `X-Amz-Expires=3600` (1h). The Drupal back-end
behind ROCK Cloud serves the same cached HTML for *hours* (header says
`cache-control: max-age=450` but `x-drupal-cache: HIT` keeps returning a
stale snapshot). So the URL you scrape off the page may already be expired.

Fix: add a query-string cache buster:

```bash
curl -s "https://cloud.rockrobotic.com/share/<uuid>?bust=$(date +%s)" -o share.html
grep -oE 'https://rockrobotic\.s3-accelerate\.amazonaws\.com[^"]*\.laz[^"]*' share.html \
  | head -1 | sed 's/&amp;/\&/g'
```

That mints a fresh URL each request. Confirmed working. We hit this bug
twice — once at the very start of the session because WebFetch's own 15-min
cache also returned a stale URL — and lost a download to it.

---

## 4. CloudCompare: the flatpak saga

We wanted CloudCompare to actually look at the LAZ before designing anything.

**First attempt — `sudo apt install -y cloudcompare`**. Installed (v2.11.3).
Opened the LAZ. Got: **"Can't guess file format: unhandled file extension 'laz'"**.

Investigation: the apt-shipped CloudCompare for Noble ships with these plugins:
`QANIMATION`, `QCOMPASS`, `QCORE_IO`, `QEDL_GL`, `QHOUGH_NORMALS`, `QPCV`,
`QPHOTOSCAN_IO`, `QRANSAC_SD`, `QSRA`. Notably **no LAS_IO plugin** — so no
LAZ (or even LAS) support. Apt doesn't ship the plugin separately either.

Options considered:
- `snap install cloudcompare` — also v2.11, same problem.
- `gh release` AppImage — none available on the GitHub release page (source-only).
- Convert LAZ → LAS via `laszip-cli` — would still need a CloudCompare with LAS support.
- **Flatpak via Flathub** — only first-party Linux build, ships v2.13.2 with full LAS/LAZ IO bundled.

We went with flatpak:

```bash
sudo apt install -y flatpak
flatpak remote-add --if-not-exists --user flathub https://flathub.org/repo/flathub.flatpakrepo
flatpak install -y --user flathub org.cloudcompare.CloudCompare
flatpak run org.cloudcompare.CloudCompare <file.laz>
```

Worked. Logged the diagnosis here so the next person doesn't repeat it.

---

## 5. PDAL + QGIS

For rasterisation: **PDAL**, the standard open-source point cloud processing
toolkit. For viewing GeoTIFFs interactively: **QGIS**.

**Gotcha:** PDAL was removed from Ubuntu Noble's default repos. `apt install
pdal` returns `E: Unable to locate package pdal`. Needs the **UbuntuGIS
unstable PPA**:

```bash
sudo add-apt-repository -y ppa:ubuntugis/ubuntugis-unstable
sudo apt update
sudo apt install -y pdal qgis
```

That ships PDAL 2.6.2 and QGIS 3.40.9. Note `python3-pdal` is **not** in
the PPA — we drive PDAL via the CLI with JSON pipelines, no Python bindings
needed.

---

## 6. The first cut — `laz_to_dem.py`

Minimal first version, two PDAL pipelines, 0.25 m grid, EPSG:32736:

- **DTM**: `filters.range Classification[2:2]` (ground), `writers.gdal output_type=min`
- **DSM**: all returns, `writers.gdal output_type=max`

Plus `gdaldem hillshade` on each for visual eyeballing in QGIS. Output went
into `l3_rolling_hills/dtm.tif`, `dsm.tif`, `dtm_hillshade.tif`,
`dsm_hillshade.tif`.

This worked first try on the L3 sample (it's pre-classified). The user
opened all four layers in QGIS and confirmed the pipeline produced sensible
output.

---

## 7. The pause + replan

Before going further the user wanted to:

(a) Confirm we're committing to DTM/DSM rasters before tuning everything to them.
(b) Send GPT/Gemini Deep Research off overnight to look for **better datasets**
    and **prior art on cost-raster recipes**.

We talked through that:

- For a ground rover, 2.5D rasters dominate because the rover lives on a 2D
  ground manifold. No reason to invent.
- The one fundamentally different paradigm worth keeping in mind is
  **topological graph extraction** (Fields2Cover-style), where tracks/rows
  are first-class graph edges rather than low-cost cells. Better for Coverage
  Path Planning, comparable-or-worse for point-to-point shortest path.
- Skipping Gazebo entirely was confirmed — see §1.

Claude drafted two deep-research prompts. They're in `research/` for posterity:

- **`research/cost-recipes-gemini.md`** — Gemini Deep Research output, 305 lines,
  8 questions covering slope, roughness, vegetation encoding, sub-cost aggregation,
  track-following bias, off-road benchmarks, planner choice, CTF-specific work.
- **`research/datasets-gemini.md`** — Gemini Deep Research output, 222 lines,
  ranked 6 candidate datasets.
- **`research/datasets-chatgpt.md`** — ChatGPT Deep Research output, 8 candidate
  datasets, more conservative + honest than Gemini ("did not find a confirmed
  CTF dataset").

---

## 8. Research takeaways that actually shaped the build

From `cost-recipes-gemini.md`:

1. **Roughness: use plane-fit residuals, not Z-stddev.** Stddev double-counts
   slope — a smooth ramp reads as "rough". Plane-fit residuals (fit a 3D
   plane to a local window, take RMS of points off the plane) decouple
   roughness from gradient. Window ≈ 1.25–1.5× vehicle footprint, then
   log-map. ← we implemented this.
2. **Bifurcated vegetation logic.** Soft linear penalty for compressible
   heights, hard lethal only for definitely-rigid obstacles. Disambiguate
   with multi-return density (porous canopy vs solid trunk). The L3 cloud
   has 7 returns; we have the data but haven't wired multi-return density
   into the cost yet.
3. **Track bias = quadratic attractive potential field.** Detect track
   centerlines → add cost trench around them, cost ∝ −k·distance². Linear
   gradients oscillate; quadratic is smooth. Galceran 2015 IROS is the
   cited source. ← not yet implemented; on the roadmap.
4. **Fields2Cover (Wageningen, open-source, ROS-compatible) natively supports
   CTF topologies** — headlands + swaths as a graph. Worth investigating
   before rolling our own coverage planner.
5. **Hybrid A\*, not plain A\***, is the literature standard for
   tractor-scale rovers. Plain A* on a grid gives 45° jagged paths that a
   diff-drive tractor literally cannot follow without pivoting (which shears
   soil). We knowingly went with plain A* for v1 because the demo is "show
   the planner picks the track" — the path-smoothness story can come later.

Honest caveat the report itself flagged:

- Standard ground-classification filters (cloth simulation, etc.) often
  smooth out narrow tractor ruts — the very thing we want to follow. SMRF
  is gentler than CSF. We chose SMRF defaults; haven't measured the
  smoothing effect explicitly yet.
- No closed-form correct weight for track bias — has to be tuned empirically.
- Static slope ≠ dynamic slip. Cost rasters can't predict wheel slip; pad
  with empirical safety buffer.

From `datasets-gemini.md` + `datasets-chatgpt.md` (cross-referenced):

Twelve total candidates considered. Top 3 we actually pursued:

| # | dataset | why |
|---|---|---|
| 1 | **RESEPI LITE XT-32 "Crop/Tree farm"** | UAV LiDAR, LAZ, RGB colourised, 50 m AGL — closest *format* match to L3. Viewable in Stitch3D before download. |
| 2 | **YellowScan Mapper+ Farmland (Scarborough UK)** | UAV LiDAR, LAS, ~80 m AGL — closest *environment* match to L3 (farm + woodland). |
| 3 | **Canterbury LINZ 2020–2025** | ALS not UAV (lower density 11.9 pts/m²) but 34,000 km² of properly classified NZ broadacre cropping. The only candidate with *confirmed paddock-scale CTF tramlines*. |

ChatGPT and Gemini disagreed on whether Canterbury was worth pursuing (it
was Gemini's #2 and ChatGPT didn't list it at all). We went with Gemini's
take here because Canterbury is the only one with confirmed paddock-scale
CTF *and* a one-click LAZ download.

---

## 9. Browsing the candidates

User downloaded 4 files. We launched them one at a time in CloudCompare
(opening multiple at once crashed at 5.7 GB free RAM):

| file | what it actually is | verdict |
|---|---|---|
| `SB40-TOPO-60SC-NOA-80magl-10ms-SACO-DomaineDesMoures.laz` | SB40 sensor, "Domaine des Moures" — French wine estate, 103M pts, 663×589 m, Lambert-93, 30 m relief | **"by far the best, really fucking good for tramlines"** |
| `MAPPERPLUS_FORE_SCRX_M300_80mAGL_8ms_SACLCO_SCARBOROUGH.laz` | YellowScan Mapper+ over UK farmland, 168M pts, 841×755 m, UTM30N, 164 m relief | "good for navigating uneven terrain but not really any good paths" |
| `VA50_URBA_NA_ULMS_150mAGL_31ms_SACL_STHIPPO.laz` | Urban corridor strip, Saint-Hippolyte FR, 248M pts, 730×1937 m, Lambert-93 | "good for navigating houses / picking route around buildings" |
| (already had) `l3_rolling_hills.laz` | the ROCK L3 sample | reference dataset |

Decision: **focus build effort on Domaine des Moures.** Vineyard with
visible tractor lanes between rows is the perfect CTF analog. Saint-Hippolyte
is interesting for an urban-routing follow-up but capstone scope says ag
first.

---

## 10. Pipeline options the user wanted explicitly considered

User asked for an honest "menu" before locking in DTM/DSM. The full
breakdown is in the chat history; the short version:

| # | approach | verdict for Domaine des Moures |
|---|---|---|
| 1 | 2.5D rasters (DTM/DSM/CHM + slope + roughness) | **chosen** — solid baseline, no overhangs to worry about |
| 2 | 2.5D + lidar intensity / RGB layer | **chosen as free upgrade** — compacted tracks reflect differently from soil/canopy, intensity is already in the LAZ |
| 3 | Multi-layer 2.5D map (GridMap / Elevation Mapping CuPy) | same theory as (1) and (2), just the ROS-native version. Defer until we add ROS. |
| 4 | 3D voxel grid / OctoMap | overkill — ground rover lives on 2D manifold, no vertical clearance reasoning needed |
| 5 | Direct point-cloud planners (RRT* / KD-tree collision) | slow per query, doesn't express "prefer X" semantics well |
| 6 | Mesh-based planners (Poisson recon + geodesic A*) | meshing is brittle, no benefit on flat-ish vineyard |
| 7 | Semantic segmentation (KPConv / RandLA-Net) | needs labels or a trained net — capstone-scope-heavy. Defer. |
| 8 | Topological / graph extraction (Fields2Cover-style) | **roadmap** — different paradigm, the *honest* CTF/vineyard solution, may beat raster cost at "always pick the track" |

For Saint-Hippolyte (urban) the answer flipped a bit: 2.5D + intensity is
still right, but **OSM gives you the road network for free** so topological
routing dominates without needing to derive it from lidar.

---

## 11. The build (`process_cloud.py` etc.)

We built 4 scripts:

### `process_cloud.py`

Inputs: a LAZ, an output dir, an optional resolution and SRS override.

Outputs (all aligned, single-band float32 GeoTIFFs):
- `dtm.tif` — bare earth, `filters.range Classification[2:2]`, `output_type=min`
- `dsm.tif` — top surface, all returns, `output_type=max`
- `intensity.tif` — mean lidar intensity. Trick: `writers.gdal output_type=mean`
  takes mean of Z, so we `filters.ferry Intensity=>Z` first to swap them.
- `chm.tif` — DSM − DTM (clamped at 0; measurement noise can flip the sign)
- `slope.tif` — `gdaldem slope`
- `roughness.tif` — plane-fit residual RMS, vectorised numpy implementation
- `hillshade.tif` — `gdaldem hillshade -az 315 -alt 45 -z 2`

**Inline ground classification.** Some clouds (e.g. Domaine des Moures) have
`Classification` all zero — no ground filter ever run. `process_cloud.py`
detects this via `pdal info --stats --dimensions=Classification` and runs
`filters.smrf` inline before the range filter if needed.

**The plane-fit residual implementation.** The literature wants
plane-fit-residual RMS over a window, not Z-stddev. Naïve approach (Python
plane fit per pixel via `scipy.linalg.lstsq` inside `scipy.ndimage.generic_filter`)
would take ~7 minutes for our 2633×2986 raster. Vectorised approach:

```python
# Pre-compute the residual-projection matrix M = I − A(AᵀA)⁻¹Aᵀ for one window
# (depends only on the window's local-coordinate grid, not the data)
# Then a single batched matmul gives residuals for every window in one go.
```

Code is in `process_cloud.py::plane_fit_residual_rms`. Runs in ~10 seconds
on the 0.25 m grid with a 5×5 (1.25 m) window.

### `build_costmap.py`

Combines the rasters into a single `cost.tif`. Logic:

1. Normalise each sub-cost linearly to `[0, 1]` against a *soft cutoff*.
2. Weighted linear sum.
3. Lethal-saturation override: any cell where slope/roughness/CHM exceeds
   its *hard cutoff* becomes `1e6` (effectively infinite cost).
4. Intensity is encoded as an *attractor*: bright cells (presumed-track)
   get low cost. Direction (`bright`/`dark`/`median`) is tunable since
   whether tracks are bright or dark depends on the sensor and surface.

Defaults:
- Weights: `slope=1.0, roughness=1.0, chm=1.0, intensity=0.5`
- Soft cutoffs: slope 10°, roughness 0.05 m, CHM 1.0 m
- Lethal cutoffs: slope 20°, roughness 0.25 m, CHM 2.0 m

On Domaine des Moures these produce ~7.7% lethal cells (the vines), which
is what we want — the planner is geometrically forced into the inter-row
corridors.

### `plan_path.py`

matplotlib click-2-points A* on the cost raster.

- Loads `cost.tif` and `hillshade.tif`.
- Downsamples cost from source 0.25 m → 1.0 m for planning (factor 4),
  using NaN-aware mean pool but treating *any* lethal pixel in the block
  as lethal in the downsampled cell. This keeps obstacles conservative.
- 8-connected A*, hand-rolled with `heapq`, ~30 lines.
- Edge cost: `step_length × (1 + 5 × cell_cost)` — a 5× weighting of
  cost vs raw distance. Tunable.
- Heuristic: Euclidean distance to goal. Admissible since cell cost ≥ 0.
- Left click sets start; second left click sets goal and runs the planner;
  right click resets; third left click starts a new plan from the new point.

Why plain A* and not Hybrid A*? Because for v1 the question is "does the
cost recipe identify the right corridors?", not "is the path
kinematically smooth?". Hybrid A* (Reeds-Shepp primitives, vehicle turning
radius) is on the roadmap.

### `preview_layers.py`

Renders an 8-panel PNG with every layer (hillshade, dtm, dsm, chm,
intensity, slope, roughness, cost). Single-shot eyeball check that the
pipeline is producing sensible numbers.

---

## 12. Gotcha — PDAL raster bounds mismatch

First run of `process_cloud.py` on Domaine des Moures crashed at the CHM
step with:

```
ValueError: operands could not be broadcast together with shapes (2359,2651) (2358,2651)
```

DTM was 2358 rows, DSM was 2359 rows. PDAL's `writers.gdal` computes its
output extent from the points that pass through the filter chain. SMRF
removed some points on the edge of the cloud, so the DTM extent was
ever-so-slightly smaller than the DSM extent.

Fix: pre-compute snapped bounds from the LAZ via `pdal info --stats` and
pass `bounds=([minx, maxx], [miny, maxy])` explicitly to every writer.
After this, every output raster is bit-identical in shape.

`process_cloud.py::laz_bounds` does the snap to the resolution grid.

---

## 13. Validation

User clicked test paths in the planner. Quote: **"ok that is fucking
amazing its working for path planning"**. Validation is informal — we
haven't yet measured "follows row vs cuts across" quantitatively, just
eyeballed.

What "validation" actually means here: the planner produces sensible
paths that bend around the lethal vine regions to use the inter-row
corridors. We haven't yet asked the harder question: does it *prefer* the
straightest inter-row corridor over cutting through any random gap, and
does the intensity layer actually pull paths toward compacted lanes vs
weed-overgrown ones.

---

## 14. Open questions / next steps

### Immediate (next session candidates)
- **Quantitative cost-tuning.** Pick 3–5 reference paths by hand on
  Domaine des Moures, then grid-search the weight vector to minimise
  divergence from those references.
- **Confirm intensity direction.** Is the brighter return the compacted
  track or the canopy in this sensor's data? Currently default is
  `intensity_prefers=bright` based on agricultural intuition; we haven't
  empirically confirmed it.
- **Save plans.** Currently no way to export a planned path as
  GeoJSON/KML. Trivial to add.
- **Multiple intermediate waypoints.** Right now it's start→goal. For a
  full mission spec it should accept N waypoints.

### Roadmap (paradigm-level)
- **Row detection.** Extract vineyard / CTF tramlines as polylines from
  the intensity raster or the CHM. Method TBD — template matching for
  parallel lines, or PCA + clustering on track-likeness pixels.
- **Track-bias quadratic attractor.** Per the literature: once rows are
  detected, generate a cost trench (cost = −k·d² where d = distance to
  nearest row centerline). Should make the planner *strongly* prefer
  rows even when off-row would be geometrically shorter.
- **Fields2Cover integration.** For true Coverage Path Planning (visit
  every row, headland turns). Drops the cost-raster paradigm entirely
  for this mode — operates on the row graph directly.
- **Hybrid A\* with vehicle kinematics.** Reeds-Shepp curves,
  minimum-turning-radius constraint. Necessary for the path to be
  actually drivable by a tractor without pivot-in-place soil shear.
- **Multi-return density layer.** Use the 7-return LAZ to compute
  "trunk vs canopy" porosity, refine the lethal/soft vegetation split
  per the literature recommendation.
- **Test on Canterbury LINZ.** Pull a small AOI from OpenTopography,
  see if the pipeline transfers from UAV-density (300+ pts/m²) to
  ALS-density (12 pts/m²). This is the cross-sensor generalisation test
  that proves the pipeline is real.

### Out of scope for capstone v1
- Real-time replanning. Static map only.
- Sensor fusion. Lidar only.
- Dynamic obstacles. Static world.
- Actual rover hardware. Simulation-of-the-planning-decision only.
- ROS2 / Nav2 / Gazebo. Deferred entirely.

---

## 15. Tool & dataset quick-reference

| tool | version | install |
|---|---|---|
| PDAL | 2.6.2 | `ppa:ubuntugis/ubuntugis-unstable` then `apt install pdal` |
| QGIS | 3.40.9 | same PPA, `apt install qgis` |
| CloudCompare | 2.13.2 | `flatpak install --user flathub org.cloudcompare.CloudCompare` |
| GDAL Python bindings | 3.11.4 | bundled with `gdal-bin` (`apt install python3-gdal`) |
| numpy/scipy/matplotlib | 1.26 / 1.11 / 3.6 | Noble defaults |

Datasets:

| name | URL | notes |
|---|---|---|
| L3 Rolling Hills | <https://cloud.rockrobotic.com/share/40e5e607-21cb-441f-85cf-d1eb882bd0e3> | 1.28 GB, 335 pts/m², EPSG:32736. Use cache-buster on share page (§3). |
| RESEPI Crop/Tree farm | <https://app.stitch3d.io/viewer/688ccf56309ee1e3bdfb5f46> | Stitch3D viewer; download path from Inertial Labs RESEPI catalogue. |
| YellowScan Mapper+ Farmland | <https://www.yellowscan.com/dataset/mapper-forestry-farm-land/> | Free registration required. |
| Canterbury LINZ 2020–25 | <https://portal.opentopography.org/lidarDataset?opentopoID=OTLAS.122022.2193.1> | Free OpenTopography account; request small AOI in mid-Canterbury for CTF. |

---

## 16. Deep-research prompts we sent off

Saved here verbatim because the synthesis text we got back is only as good
as the prompts we wrote.

### Prompt A — alternative datasets

> Search task: find UAV-lidar (and similar) datasets of farmland,
> especially controlled traffic farming, comparable to a ROCK Robotic /
> DJI Zenmuse L3 sample. *Context, reference dataset spec, what we're
> looking for (UAV ~100 pts/m² preferred, ALS ≥10 pts/m² acceptable
> fallback), priorities (CTF visible > L3-similar > AU/NZ preferred >
> all access tiers), search vectors (gov data, university repos, vendor
> sample catalogues, OpenTopography, academic supplementary data),
> deliverable (ranked markdown table)…*

Full prompt in chat history; full output in `research/datasets-gemini.md`
and `research/datasets-chatgpt.md`.

### Prompt B — cost-raster prior art

> Research task: off-road / outdoor robot path planning — cost-raster
> recipes and traversability estimation, with emphasis on biasing
> planners toward existing vehicle tracks. *8 specific questions: slope
> cost functional forms, roughness metrics, vegetation encoding,
> sub-cost aggregation, track-following bias, off-road benchmarks,
> planner choice, CTF-specific work. Deliverable: question-by-question
> answers with citations, recommended starting recipe, top 3 papers,
> blind spots…*

Full output in `research/cost-recipes-gemini.md`.

---

## 17. Memory notes (for future Claude sessions)

The persistent memory dir at `~/.claude/projects/-home-knucky-rover-team-map/memory/`
has these load-bearing notes:

- `user_profile.md` — capstone student, partner Anton, direct comms style.
- `project_scope_planner_not_gazebo.md` — the pivot record (no Gazebo).
- `project_dataset.md` — L3 Rolling Hills facts.
- `feedback_drive_installs.md` — user wants me to drive installs and ask for sudo when needed; Bash tool can't escalate.
- `reference_rock_share_caching.md` — the share-page cache-buster trick.

If you (future Claude) load this repo cold, those memories will already be
in context. This `context.md` is the human-readable mirror.

---

## 18. Decision log — the short version

| date | decision | why |
|---|---|---|
| 2026-05-28 | LAZ at 0.25 m, EPSG of source | dense enough to resolve tractor wheel ruts (~30 cm), small enough that whole-site rasters are ~30 MB |
| 2026-05-28 | Dropped Gazebo + teleop | user spotted tracks and pivoted scope to "planner that picks tracks" |
| 2026-05-28 | DTM/DSM via PDAL not LASTools | open source, JSON pipeline, in apt |
| 2026-05-28 | CloudCompare via flatpak | only Linux build with LAS_IO plugin |
| 2026-05-29 | Domaine des Moures as primary dataset | best CTF-tramline visual we have |
| 2026-05-29 | Plane-fit residuals over Z-stddev | decouples roughness from slope (literature) |
| 2026-05-29 | Intensity as a free attractor layer | tracks reflect differently; data already in LAZ |
| 2026-05-29 | Inline SMRF when cloud unclassified | preserves narrow ruts better than CSF |
| 2026-05-29 | Pre-snapped bounds passed to every PDAL writer | fixes raster shape mismatch from SMRF edge-pruning |
| 2026-05-29 | Plain A* + 1 m downsampled grid | interactive (<1 s) and enough to validate cost recipe |
| 2026-05-29 | Hybrid A* + Fields2Cover deferred to roadmap | needed for kinematic feasibility + true CPP, but v1 demo doesn't need them |

---

*end of context.md*
