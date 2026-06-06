# Data sources — gitignored point clouds & rasters

The `.laz` / `.las` point clouds and generated `.tif` rasters are **not** stored
in git (see `.gitignore`). They are large but **re-downloadable** — every one is
a public vendor/agency sample. Full provenance and selection notes live in
[`context.md`](context.md) §8–9 and [`research/datasets-chatgpt.md`](research/datasets-chatgpt.md).
This file is the quick recovery index for a fresh machine after the disk reset.

> Regenerate rasters from a `.laz` with: `process_cloud.py` → `build_costmap.py`
> (see `README.md`).

| File (in repo root) | What it is | Where to get it again |
|---|---|---|
| `l3_rolling_hills/` (~1.4G) | ROCK Robotic "Rolling Hills" L3 public sample (DJI Zenmuse L3) — reference dataset | ROCK Robotic share page <https://cloud.rockrobotic.com/share/40e5e607-21cb-441f-85cf-d1eb882bd0e3> — see the curl-the-share-page recipe in `context.md`/`README.md` |
| `SB40-TOPO-60SC-NOA-80magl-10ms-SACO-DomaineDesMoures.laz` (1.2G) | UAV-LiDAR vendor sample, "Domaine des Moures" French wine estate (103M pts, Lambert-93). **The primary build dataset** (best tramlines) | Vendor sample catalogue — see `context.md` §8–9 and `research/datasets-chatgpt.md` |
| `MAPPERPLUS_FORE_SCRX_M300_80mAGL_8ms_SACLCO_SCARBOROUGH.laz` (1.5G) | YellowScan Mapper+ sample over UK farmland, Scarborough (168M pts, UTM30N) | YellowScan dataset catalogue <https://www.yellowscan.com/dataset/> ("Download .Las") |
| `VA50_URBA_NA_ULMS_150mAGL_31ms_SACL_STHIPPO.laz` (1.4G) | UAV-LiDAR vendor sample, urban corridor, Saint-Hippolyte FR (248M pts, Lambert-93) | Vendor sample catalogue — see `context.md` §8–9 and `research/datasets-chatgpt.md` |
| `domaine_des_moures/` (~135M) | Derived products from the SB40 Domaine des Moures cloud above | Generated locally from the `.laz` |

## Related dataset in the `system` repo

Robotics localisation work also used USGS open LiDAR, gitignored at
`system/alex/domain/rob/rover/p1/loc/map/`:

| File | What it is | Where to get it again |
|---|---|---|
| `USGS_LPC_MA_CentralEastern_2021_B21_19TBG250656.laz` / `.zip` | USGS 3DEP LiDAR Point Cloud, Massachusetts Central Eastern 2021, tile `19TBG250656` (public domain) | USGS 3DEP / The National Map <https://apps.nationalmap.gov/downloader/> — search the tile ID |

---
*Created 2026-06-06 during the pre-reset disk audit. All sources confirmed
re-downloadable, so the local copies are safe to let the wipe remove.*
