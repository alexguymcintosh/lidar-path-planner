#!/usr/bin/env python3
"""
Rasterise an unclassified LAZ into the layer stack we need for cost-raster planning.

Output (all single-band float32 GeoTIFFs, aligned, same grid):
  dtm.tif         bare-earth elevation
  dsm.tif         top-surface elevation
  intensity.tif   mean lidar intensity
  chm.tif         dsm - dtm (canopy/vegetation height)
  slope.tif       slope in degrees, from DTM via gdaldem
  roughness.tif   plane-fit residual RMS (decoupled from slope)
  hillshade.tif   shaded relief from DTM, for visualisation

If the cloud is unclassified (Classification all zero), runs SMRF ground filter
inline. If it's already classified, just trusts class=2.
"""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from osgeo import gdal

gdal.UseExceptions()


def run_pdal(pipe: dict, tag: str) -> None:
    print(f"  [{tag}] running pdal pipeline", flush=True)
    proc = subprocess.run(
        ["pdal", "pipeline", "--stdin"],
        input=json.dumps(pipe),
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        print(proc.stdout)
        print(proc.stderr, file=sys.stderr)
        sys.exit(f"  [{tag}] pdal failed (exit {proc.returncode})")


def gdal_writer(filename: str, res: float, output_type: str, srs: str | None,
                bounds: str | None = None) -> dict:
    w = {
        "type": "writers.gdal",
        "filename": filename,
        "resolution": res,
        "output_type": output_type,
        "gdaldriver": "GTiff",
        "data_type": "float32",
        "window_size": 3,
        "nodata": -9999,
    }
    if srs:
        w["default_srs"] = srs
    if bounds:
        w["bounds"] = bounds
    return w


def laz_bounds(laz: Path, res: float) -> str:
    """Compute snapped bounds string for PDAL writers.gdal so all rasters align."""
    out = subprocess.check_output(["pdal", "info", str(laz), "--stats"], text=True)
    d = json.loads(out)
    stats = {s["name"]: s for s in d["stats"]["statistic"]}
    minx, miny = stats["X"]["minimum"], stats["Y"]["minimum"]
    maxx, maxy = stats["X"]["maximum"], stats["Y"]["maximum"]
    # Snap to res grid so all writers produce identical extents
    minx = res * (minx // res)
    miny = res * (miny // res)
    maxx = res * ((maxx // res) + 1)
    maxy = res * ((maxy // res) + 1)
    return f"([{minx}, {maxx}], [{miny}, {maxy}])"


def needs_classification(laz: Path) -> bool:
    """Check if the cloud has any class-2 ground points."""
    out = subprocess.check_output(
        ["pdal", "info", str(laz), "--stats", "--dimensions=Classification"],
        text=True,
    )
    d = json.loads(out)
    s = d["stats"]["statistic"][0]
    return s["maximum"] == 0 and s["minimum"] == 0


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
    out.FlushCache()


def plane_fit_residual_rms(z: np.ndarray, win: int = 5) -> np.ndarray:
    """
    For each pixel, fit a plane to its win x win neighbourhood and return the
    RMS residual. Vectorised: builds the residual-projection matrix once, then
    does one big matmul over all windows.

    Decouples roughness from underlying slope (the literature recommendation
    over plain Z-stddev).
    """
    h, w = z.shape
    if win % 2 == 0:
        raise ValueError("win must be odd")
    pad = win // 2
    # Pad with edge values so output keeps the same shape (NaN-aware)
    zp = np.pad(z, pad, mode="edge").astype(np.float64)

    # Build the design matrix for one window: A = [1, dx, dy]
    grid = np.arange(-pad, pad + 1)
    dx, dy = np.meshgrid(grid, grid, indexing="xy")
    A = np.column_stack([np.ones(win * win), dx.ravel(), dy.ravel()])  # (N, 3)
    # Residual-projection matrix M = I - A (A^T A)^{-1} A^T
    M = np.eye(win * win) - A @ np.linalg.pinv(A.T @ A) @ A.T  # (N, N)

    # All windows as a (h, w, win, win) view, flatten last two dims
    windows = sliding_window_view(zp, (win, win))  # (h, w, win, win)
    flat = windows.reshape(-1, win * win)  # (h*w, N)

    # Skip windows that contain NaN
    nan_mask = np.isnan(flat).any(axis=1)
    flat_safe = np.where(nan_mask[:, None], 0.0, flat)

    residuals = flat_safe @ M.T  # (h*w, N)
    rms = np.sqrt(np.mean(residuals**2, axis=1))
    rms[nan_mask] = np.nan
    return rms.reshape(h, w).astype(np.float32)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("laz", type=Path)
    ap.add_argument("out_dir", type=Path)
    ap.add_argument("--res", type=float, default=0.25)
    ap.add_argument("--srs", type=str, default=None,
                    help="EPSG override, e.g. EPSG:2154. If absent, use LAZ's own SRS.")
    ap.add_argument("--roughness-window", type=int, default=5,
                    help="Plane-fit window size in pixels (odd). 5 @ 0.25m = 1.25m footprint.")
    args = ap.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    laz = str(args.laz)

    classify = needs_classification(args.laz)
    print(f"cloud classification: {'absent — will run SMRF' if classify else 'present — using class 2'}")

    bounds = laz_bounds(args.laz, args.res)
    print(f"snapped bounds for raster alignment: {bounds}")

    # ---- DTM ---------------------------------------------------------------
    dtm_path = args.out_dir / "dtm.tif"
    stages: list = [laz]
    if classify:
        # Reclassify in place then keep ground only
        stages.append({"type": "filters.assign", "assignment": "Classification[:]=0"})
        stages.append({"type": "filters.smrf"})  # tags class 2 as ground
    stages.append({"type": "filters.range", "limits": "Classification[2:2]"})
    stages.append(gdal_writer(str(dtm_path), args.res, "min", args.srs, bounds))
    run_pdal({"pipeline": stages}, "DTM")

    # ---- DSM ---------------------------------------------------------------
    dsm_path = args.out_dir / "dsm.tif"
    run_pdal({"pipeline": [laz, gdal_writer(str(dsm_path), args.res, "max", args.srs, bounds)]}, "DSM")

    # ---- Intensity ---------------------------------------------------------
    # writers.gdal output_type="mean" rasterises mean of Z per cell — we want mean
    # intensity instead. Use filters.ferry to copy Intensity into Z, then mean.
    int_path = args.out_dir / "intensity.tif"
    run_pdal({"pipeline": [
        laz,
        {"type": "filters.ferry", "dimensions": "Intensity=>Z"},
        gdal_writer(str(int_path), args.res, "mean", args.srs, bounds),
    ]}, "Intensity")

    # ---- Derived layers (in numpy) ----------------------------------------
    dtm, dtm_ds = read_raster(dtm_path)
    dsm, _ = read_raster(dsm_path)

    print("  [CHM]  dsm - dtm")
    chm = dsm - dtm
    chm = np.where(chm < 0, 0, chm)  # measurement noise can flip the sign
    write_raster_like(args.out_dir / "chm.tif", chm, dtm_ds)

    print("  [Roughness]  plane-fit residual RMS")
    rough = plane_fit_residual_rms(dtm, win=args.roughness_window)
    write_raster_like(args.out_dir / "roughness.tif", rough, dtm_ds)

    # ---- gdaldem layers ----------------------------------------------------
    print("  [Slope]  gdaldem slope")
    subprocess.run(
        ["gdaldem", "slope", str(dtm_path), str(args.out_dir / "slope.tif"),
         "-compute_edges", "-q"],
        check=True,
    )
    print("  [Hillshade]  gdaldem hillshade")
    subprocess.run(
        ["gdaldem", "hillshade", str(dtm_path), str(args.out_dir / "hillshade.tif"),
         "-az", "315", "-alt", "45", "-z", "2", "-compute_edges", "-q"],
        check=True,
    )

    print(f"done. layers in {args.out_dir}/")
    for p in sorted(args.out_dir.glob("*.tif")):
        size_mb = p.stat().st_size / 1024**2
        print(f"  {p.name:18s} {size_mb:6.1f} MB")


if __name__ == "__main__":
    main()
