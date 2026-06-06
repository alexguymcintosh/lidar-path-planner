# Data sources — gitignored point clouds & rasters

The `.laz` / `.las` point clouds and generated `.tif` rasters are **not** stored
in git (see `.gitignore`). They are large and regenerable. This file records
where each source dataset came from so the pipeline can be rebuilt on a fresh
machine after the disk is reset.

> Regenerate rasters from a `.laz` with: `process_cloud.py` → `build_costmap.py`
> (see `README.md`).

| File (in repo root) | Size | What it is | Source |
|---|---|---|---|
| `l3_rolling_hills/` | ~1.4G | DJI Zenmuse L3 public sample, "L3 Rolling Hills" — the primary dev dataset | **ROCK Robotic** public sample library — <FILL IN exact download URL> |
| `MAPPERPLUS_FORE_SCRX_M300_80mAGL_8ms_SACLCO_SCARBOROUGH.laz` | 1.5G | UAV LiDAR, DJI Matrice 300 (M300), 80 m AGL @ 8 m/s, Scarborough site | Partner drone capture (Anton?) — <FILL IN: who provided it / where stored> |
| `SB40-TOPO-60SC-NOA-80magl-10ms-SACO-DomaineDesMoures.laz` | 1.2G | UAV LiDAR, 80 m AGL @ 10 m/s, Domaine Des Moures site | Partner drone capture — <FILL IN: who provided it / where stored> |
| `VA50_URBA_NA_ULMS_150mAGL_31ms_SACL_STHIPPO.laz` | 1.4G | UAV LiDAR, 150 m AGL @ 31 m/s, St Hippolyte site | Partner drone capture — <FILL IN: who provided it / where stored> |
| `domaine_des_moures/` | ~135M | Derived products from the SB40 Domaine Des Moures capture above | Generated locally from `SB40-…-DomaineDesMoures.laz` |

## Related dataset in the `system` repo

The robotics localisation work also used USGS open LiDAR, stored (gitignored) at
`system/alex/domain/rob/rover/p1/loc/map/`:

| File | What it is | Source |
|---|---|---|
| `USGS_LPC_MA_CentralEastern_2021_B21_19TBG250656.laz` / `.zip` | USGS 3DEP LiDAR Point Cloud, Massachusetts Central Eastern 2021, tile `19TBG250656` | **USGS 3DEP / The National Map** — public domain. Re-download from <https://apps.nationalmap.gov/downloader/> (search the tile ID) |

---
*Created 2026-06-06 during the pre-reset disk audit. The `<FILL IN>` markers are
the only things I couldn't determine from the disk — fill them with the exact
URLs / partner attribution before the wipe so nothing is unrecoverable.*
