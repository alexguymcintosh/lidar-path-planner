#!/usr/bin/env python3
"""
Combine per-layer rasters into a single cost.tif for path planning.

Recipe (from the literature synthesis):
  - Normalise each sub-cost to [0, 1] over its useful range
  - Weighted linear sum
  - Lethal-saturation override: if ANY sub-cost trips its hard cutoff, the cell
    becomes infinite (np.inf in the .tif, which we encode as a large finite value
    for GDAL but flag with a separate lethal-mask raster too).

Defaults are agricultural-rover sensible. Tunable via --weights / --lethal flags.

Sub-costs and their lethal cutoffs:
  slope (deg)         soft up to 10°, lethal at 20°
  roughness (m, RMS)  soft up to 0.05 m, lethal at 0.25 m
  chm (m)             soft up to 1.0 m, lethal at 2.0 m
  intensity-track     NEGATIVE cost (attractor) — bright/dark tracks pull paths

Intensity handling: tracks tend to be brighter (compacted soil) than canopy or
loose ground. We compute "track-likeness" as the absolute distance of cell
intensity from the median, scaled so high distances → low cost (attractor).
For now we use a simple "the brighter the better" heuristic with a configurable
direction flag, since whether tracks are bright or dark depends on the sensor
and the surface.
"""

import argparse
from pathlib import Path

import numpy as np
from osgeo import gdal

gdal.UseExceptions()

LETHAL_VALUE = 1e6  # encoded as finite for GDAL, treated as ∞ by the planner


def read_raster(path: Path) -> tuple[np.ndarray, gdal.Dataset]:
    ds = gdal.Open(str(path))
    arr = ds.GetRasterBand(1).ReadAsArray().astype(np.float32)
    nodata = ds.GetRasterBand(1).GetNoDataValue()
    if nodata is not None:
        arr = np.where(arr == nodata, np.nan, arr)
    return arr, ds


def write_raster_like(path: Path, arr: np.ndarray, template: gdal.Dataset, nodata: float = -9999) -> None:
    arr_out = np.where(np.isnan(arr), nodata, arr).astype(np.float32)
    driver = gdal.GetDriverByName("GTiff")
    out = driver.Create(
        str(path), arr.shape[1], arr.shape[0], 1, gdal.GDT_Float32,
        options=["COMPRESS=DEFLATE", "PREDICTOR=2", "TILED=YES"],
    )
    out.SetGeoTransform(template.GetGeoTransform())
    out.SetProjection(template.GetProjection())
    band = out.GetRasterBand(1)
    band.WriteArray(arr_out)
    band.SetNoDataValue(nodata)
    band.FlushCache()


def normalise(arr: np.ndarray, soft: float) -> np.ndarray:
    """Linear ramp to [0, 1] up to `soft`. Values >= soft are clipped to 1."""
    return np.clip(arr / soft, 0.0, 1.0)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("layers_dir", type=Path)
    ap.add_argument("--weights", type=str,
                    default="slope=1.0,roughness=1.0,chm=1.0,intensity=0.5",
                    help='comma-separated key=value pairs')
    ap.add_argument("--soft-slope", type=float, default=10.0)
    ap.add_argument("--soft-roughness", type=float, default=0.05)
    ap.add_argument("--soft-chm", type=float, default=1.0)
    ap.add_argument("--lethal-slope", type=float, default=20.0)
    ap.add_argument("--lethal-roughness", type=float, default=0.25)
    ap.add_argument("--lethal-chm", type=float, default=2.0)
    ap.add_argument("--intensity-prefers", choices=["bright", "dark", "median"], default="bright",
                    help='whether tracks are brighter (bright), darker (dark), '
                         'or just less-noisy than surrounds (median)')
    args = ap.parse_args()

    weights = dict(item.split("=") for item in args.weights.split(","))
    weights = {k: float(v) for k, v in weights.items()}

    slope, ref = read_raster(args.layers_dir / "slope.tif")
    rough, _ = read_raster(args.layers_dir / "roughness.tif")
    chm, _ = read_raster(args.layers_dir / "chm.tif")
    intensity, _ = read_raster(args.layers_dir / "intensity.tif")

    # Per-layer normalised costs
    c_slope = normalise(slope, args.soft_slope)
    c_rough = normalise(rough, args.soft_roughness)
    c_chm = normalise(chm, args.soft_chm)

    # Intensity → cost (attractor: bright tracks → low cost)
    valid = ~np.isnan(intensity)
    int_lo, int_hi = np.nanpercentile(intensity[valid], [5, 95])
    int_norm = np.clip((intensity - int_lo) / max(int_hi - int_lo, 1e-6), 0.0, 1.0)
    if args.intensity_prefers == "bright":
        c_int = 1.0 - int_norm
    elif args.intensity_prefers == "dark":
        c_int = int_norm
    else:  # median: away from the median is rough/edgy → costly
        med = np.nanmedian(intensity)
        c_int = np.clip(np.abs(intensity - med) / max(int_hi - int_lo, 1e-6), 0.0, 1.0)

    # Lethal mask
    lethal = (
        (slope > args.lethal_slope)
        | (rough > args.lethal_roughness)
        | (chm > args.lethal_chm)
    )

    # Weighted sum (treat NaN as lethal too)
    cost = (
        weights.get("slope", 1.0) * c_slope
        + weights.get("roughness", 1.0) * c_rough
        + weights.get("chm", 1.0) * c_chm
        + weights.get("intensity", 0.5) * c_int
    )
    total_w = sum(weights.values())
    cost = cost / max(total_w, 1e-6)  # back in [0, 1] range
    cost = np.where(lethal | np.isnan(cost), LETHAL_VALUE, cost)

    out = args.layers_dir / "cost.tif"
    write_raster_like(out, cost, ref)
    lethal_out = args.layers_dir / "lethal_mask.tif"
    write_raster_like(lethal_out, lethal.astype(np.float32), ref)

    # Stats
    finite = cost[cost < LETHAL_VALUE]
    print(f"cost raster: {out}")
    print(f"  shape {cost.shape}, lethal cells: {lethal.sum():,} / {cost.size:,} "
          f"({100*lethal.sum()/cost.size:.1f}%)")
    if finite.size:
        print(f"  finite cost: min={finite.min():.3f}  median={np.median(finite):.3f}  "
              f"max={finite.max():.3f}")
    print(f"  weights={weights}  intensity_prefers={args.intensity_prefers}")


if __name__ == "__main__":
    main()
