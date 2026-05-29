#!/usr/bin/env python3
"""
Rasterise the L3 Rolling Hills LAZ into a DTM (bare earth) and DSM (top surface).

DTM: classification=2 (ground), output min-Z per cell, small-window aggregation
     to fill 1-cell pinholes. NoData stays where ground returns are absent.
DSM: all returns, max-Z per cell.

Both written as single-band float32 GeoTIFFs in EPSG:32736.
"""

import json
import subprocess
import sys
from pathlib import Path

LAZ = Path("/home/knucky-rover-team/map/l3_rolling_hills/l3_rolling_hills.laz")
OUT_DIR = LAZ.parent
RES = 0.25  # metres per pixel
SRS = "EPSG:32736"


def pipeline(filename: str, output_type: str, classification_filter: bool) -> dict:
    stages: list = [str(LAZ)]
    if classification_filter:
        stages.append({"type": "filters.range", "limits": "Classification[2:2]"})
    stages.append({
        "type": "writers.gdal",
        "filename": filename,
        "resolution": RES,
        "output_type": output_type,
        "gdaldriver": "GTiff",
        "data_type": "float32",
        "default_srs": SRS,
        "window_size": 3,
        "nodata": -9999,
    })
    return {"pipeline": stages}


def run(name: str, pipe: dict) -> None:
    print(f"[{name}] starting pdal pipeline", flush=True)
    proc = subprocess.run(
        ["pdal", "pipeline", "--stdin"],
        input=json.dumps(pipe),
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        print(proc.stdout)
        print(proc.stderr, file=sys.stderr)
        sys.exit(f"[{name}] pdal failed (exit {proc.returncode})")
    print(f"[{name}] done -> {pipe['pipeline'][-1]['filename']}", flush=True)


def main() -> None:
    if not LAZ.exists():
        sys.exit(f"LAZ not found: {LAZ}")
    run("DTM", pipeline(str(OUT_DIR / "dtm.tif"), "min", classification_filter=True))
    run("DSM", pipeline(str(OUT_DIR / "dsm.tif"), "max", classification_filter=False))


if __name__ == "__main__":
    main()
