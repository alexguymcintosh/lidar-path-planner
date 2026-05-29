# lidar-path-planner

Outdoor lidar path-planning for a tractor-scale rover. Takes a UAV-lidar point
cloud, derives a multi-layer cost raster, runs A* on it, and lets you click
two waypoints to plan a route that prefers existing vehicle tracks over
straight-line cuts across paddocks.

Built as a robotics capstone project. Designed against the ROCK Robotic "L3
Rolling Hills" public sample (DJI Zenmuse L3), with the intent that the
pipeline drops in cleanly when partner Anton's drone-captured data arrives.

## Status

- ✅ LAZ → DTM / DSM / CHM / slope / roughness / intensity / hillshade rasters
- ✅ Weighted-sum cost raster with lethal-saturation override
- ✅ Click-2-points A* planner with matplotlib UI
- ⏳ Row detection (extract vineyard / CTF tramlines as polylines)
- ⏳ Coverage path planning (Fields2Cover integration or boustrophedon)
- ⏳ Hybrid A* with vehicle kinematic constraints
- ⏳ Track-bias quadratic attractor potential field

See [`context.md`](context.md) for the verbose history — every decision,
pivot, and gotcha that got us here. See [`research/`](research/) for the
deep-research reports that informed the cost-raster recipe and dataset
shortlist.

## Pipeline

```
        LAZ point cloud
              │
              ▼
   process_cloud.py  (PDAL + numpy + gdaldem)
              │
              ▼
   ┌──────────────────────────────────────────────┐
   │ dtm.tif   dsm.tif   chm.tif   slope.tif      │
   │ roughness.tif   intensity.tif   hillshade.tif│
   └──────────────────────────────────────────────┘
              │
              ▼
   build_costmap.py  (weighted sum + lethal override)
              │
              ▼
          cost.tif + lethal_mask.tif
              │
              ▼
   plan_path.py  (click-2-points A* UI)
              │
              ▼
        rover-traversable path
```

## Quickstart

### Dependencies

```
sudo add-apt-repository -y ppa:ubuntugis/ubuntugis-unstable
sudo apt update
sudo apt install -y pdal qgis python3-scipy python3-matplotlib python3-gdal
sudo apt install -y flatpak                                  # for CloudCompare (LAZ viewing)
flatpak install -y --user flathub org.cloudcompare.CloudCompare
```

### Get a point cloud

Anything in `.laz` works. The L3 Rolling Hills sample we used:

```
mkdir -p l3_rolling_hills && cd l3_rolling_hills
curl -s "https://cloud.rockrobotic.com/share/40e5e607-21cb-441f-85cf-d1eb882bd0e3?bust=$(date +%s)" -o share.html
URL=$(grep -oE 'https://rockrobotic\.s3-accelerate\.amazonaws\.com[^"]*\.laz[^"]*' share.html | head -1 | sed 's/&amp;/\&/g')
curl -L -o l3_rolling_hills.laz "$URL"
```

(The presigned URL expires after 1 hour and is server-cached for ~7 hours,
hence the cache-buster query param. See `context.md` for why this is needed.)

### Run the pipeline

```
python3 process_cloud.py l3_rolling_hills/l3_rolling_hills.laz l3_rolling_hills/
python3 build_costmap.py l3_rolling_hills/
python3 preview_layers.py l3_rolling_hills/        # optional 8-panel PNG montage
python3 plan_path.py l3_rolling_hills/             # interactive matplotlib UI
```

### Tune the cost raster

```
python3 build_costmap.py l3_rolling_hills/ \
    --weights slope=0.5,roughness=0.5,chm=2.0,intensity=2.0 \
    --intensity-prefers bright \
    --lethal-slope 25 --lethal-chm 1.5
```

Then re-run `plan_path.py` to see the effect.

## Scripts

| file | what it does |
|---|---|
| `process_cloud.py` | LAZ → 7 aligned GeoTIFF rasters. Runs SMRF ground-classification inline if the cloud lacks Classification dimension. Plane-fit residual roughness in vectorised numpy (decoupled from slope, per literature). |
| `build_costmap.py` | Weighted sum of normalised sub-costs (slope, roughness, CHM, intensity) with hard lethal cutoffs. All weights and thresholds tunable via CLI. |
| `plan_path.py` | matplotlib click-to-plan A* UI on the cost raster. Downsamples for interactive speed; lethal cells refuse. |
| `preview_layers.py` | 8-panel PNG of every layer for sanity-checking the pipeline. |
| `laz_to_dem.py` | Older minimal DTM+DSM-only script (kept for reference; superseded by `process_cloud.py`). |

## Why a cost raster + A*

For a tractor-scale ground rover, the rover lives on a 2D ground manifold —
2.5D rasters are the *right* representation, not just the easy one. The full
analysis of every alternative (3D voxel grids, mesh planners, direct
point-cloud planners, semantic segmentation, topological graph extraction,
etc.) is in [`context.md`](context.md) under §"Pipeline options considered".

The one alternative paradigm worth keeping on the roadmap is **topological
graph extraction** (Fields2Cover-style) — fundamentally different from cost
rasters in that it treats tracks as first-class edges rather than as
low-cost regions. Best for true Coverage Path Planning, which is a different
problem than shortest-path A* between two waypoints.

## License

CC BY 4.0 for everything in `research/` (per the OpenTopography terms on
the data those reports cited; the synthesis text was produced by ChatGPT /
Gemini Deep Research from prompts in `context.md` §"Deep research prompts").
Source code MIT.
