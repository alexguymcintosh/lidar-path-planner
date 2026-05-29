#!/usr/bin/env python3
"""Render a multi-panel PNG showing each layer of the pipeline. Useful for eyeballing."""

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LogNorm
from osgeo import gdal

gdal.UseExceptions()

LETHAL_T = 5e5


def load(p: Path):
    ds = gdal.Open(str(p))
    arr = ds.GetRasterBand(1).ReadAsArray().astype(np.float32)
    nd = ds.GetRasterBand(1).GetNoDataValue()
    if nd is not None:
        arr = np.where(arr == nd, np.nan, arr)
    return arr


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: preview_layers.py <layers_dir>")
    d = Path(sys.argv[1])
    layers = ["hillshade", "dtm", "dsm", "chm", "intensity", "slope", "roughness", "cost"]
    cmaps = {"hillshade": "gray", "dtm": "terrain", "dsm": "terrain", "chm": "Greens",
             "intensity": "gray", "slope": "magma", "roughness": "magma", "cost": "turbo"}

    fig, axes = plt.subplots(2, 4, figsize=(20, 10), constrained_layout=True)
    for ax, name in zip(axes.flat, layers):
        p = d / f"{name}.tif"
        if not p.exists():
            ax.set_title(f"{name} (missing)"); ax.axis("off"); continue
        arr = load(p)
        # Mask lethal for cost
        if name == "cost":
            arr_disp = np.where(arr >= LETHAL_T, np.nan, arr)
            lethal = np.where(arr >= LETHAL_T, 1.0, np.nan)
            im = ax.imshow(arr_disp, cmap=cmaps[name],
                           vmin=np.nanpercentile(arr_disp, 2),
                           vmax=np.nanpercentile(arr_disp, 98))
            ax.imshow(lethal, cmap="Greys", alpha=0.7, vmin=0, vmax=1)
        else:
            vmin = np.nanpercentile(arr, 2)
            vmax = np.nanpercentile(arr, 98)
            im = ax.imshow(arr, cmap=cmaps[name], vmin=vmin, vmax=vmax)
        plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
        finite = arr[np.isfinite(arr) & (arr < LETHAL_T)]
        if finite.size:
            ax.set_title(f"{name}\nmin {np.nanmin(finite):.3f}  med {np.nanmedian(finite):.3f}  "
                         f"max {np.nanmax(finite):.3f}", fontsize=10)
        else:
            ax.set_title(name)
        ax.set_xticks([]); ax.set_yticks([])

    fig.suptitle(f"Layer stack: {d}", fontsize=14)
    out = d / "preview.png"
    fig.savefig(out, dpi=110, bbox_inches="tight")
    print(f"saved -> {out}")


if __name__ == "__main__":
    main()
