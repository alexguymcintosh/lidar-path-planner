#!/usr/bin/env python3
"""
Click-two-points A* path planner over a cost raster.

Usage:
  python3 plan_path.py domaine_des_moures/
    -> opens hillshade with cost overlay; first click = start, second = goal,
       A* runs, path drawn. Right-click resets. Close window to quit.

Background = hillshade.tif if present, else cost.tif.
Overlay    = cost.tif with transparency (red = costly, blue = cheap).
Lethal cells are dark grey, untraversable.

For interactive speed the planner runs at a downsampled resolution
(--plan-res 1.0 m by default) — pixel coords are mapped back to display.
"""

import argparse
import heapq
import sys
from dataclasses import dataclass
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LinearSegmentedColormap, Normalize
from matplotlib.patches import Circle
from osgeo import gdal

gdal.UseExceptions()

LETHAL = 1e6
LETHAL_THRESHOLD = LETHAL / 2  # anything above this is treated as infinite cost


def load_raster(path: Path) -> tuple[np.ndarray, tuple]:
    ds = gdal.Open(str(path))
    arr = ds.GetRasterBand(1).ReadAsArray().astype(np.float32)
    nodata = ds.GetRasterBand(1).GetNoDataValue()
    if nodata is not None:
        arr = np.where(arr == nodata, np.nan, arr)
    gt = ds.GetGeoTransform()
    return arr, gt


def downsample(arr: np.ndarray, factor: int) -> np.ndarray:
    """Mean-pool with NaN-aware reduction, factor x factor."""
    if factor == 1:
        return arr
    h, w = arr.shape
    h2, w2 = h // factor, w // factor
    arr = arr[: h2 * factor, : w2 * factor]
    arr = arr.reshape(h2, factor, w2, factor)
    # If any block contains a lethal value, the pooled cell is lethal too
    lethal_block = (arr >= LETHAL_THRESHOLD).any(axis=(1, 3))
    pooled = np.nanmean(arr, axis=(1, 3))
    pooled = np.where(lethal_block, LETHAL, pooled)
    return pooled


@dataclass
class Grid:
    cost: np.ndarray       # (H, W), finite or LETHAL
    cell_size_m: float
    h: int
    w: int


def astar(grid: Grid, start: tuple[int, int], goal: tuple[int, int]) -> list[tuple[int, int]] | None:
    """8-connected A* on a 2D cost grid. cost[r,c] is the cost of *entering* (r,c)."""
    H, W = grid.h, grid.w
    if not (0 <= start[0] < H and 0 <= start[1] < W):
        return None
    if not (0 <= goal[0] < H and 0 <= goal[1] < W):
        return None
    if grid.cost[start] >= LETHAL_THRESHOLD or grid.cost[goal] >= LETHAL_THRESHOLD:
        return None

    # 8-connected neighbours and their step lengths (cells)
    neighbours = [(-1, -1, 1.4142), (-1, 0, 1.0), (-1, 1, 1.4142),
                  (0, -1, 1.0),                    (0, 1, 1.0),
                  (1, -1, 1.4142),  (1, 0, 1.0),  (1, 1, 1.4142)]

    def h(rc):
        return np.hypot(rc[0] - goal[0], rc[1] - goal[1])  # admissible Chebyshev/Euclid

    open_heap = [(h(start), 0.0, start, None)]  # (f, g, node, parent_key)
    came_from = {start: None}
    g_score = {start: 0.0}

    while open_heap:
        f, g, node, _ = heapq.heappop(open_heap)
        if node == goal:
            # Reconstruct path
            path = []
            cur = node
            while cur is not None:
                path.append(cur)
                cur = came_from[cur]
            path.reverse()
            return path
        if g > g_score.get(node, float("inf")):
            continue
        r, c = node
        for dr, dc, step in neighbours:
            nr, nc = r + dr, c + dc
            if not (0 <= nr < H and 0 <= nc < W):
                continue
            ncost = grid.cost[nr, nc]
            if ncost >= LETHAL_THRESHOLD or np.isnan(ncost):
                continue
            # Per-cell cost weighted by step length and a base distance term
            # so paths still prefer shorter routes when costs are tied.
            edge = step * (1.0 + 5.0 * ncost)  # 5x cost weighting vs distance
            tentative_g = g + edge
            if tentative_g < g_score.get((nr, nc), float("inf")):
                g_score[(nr, nc)] = tentative_g
                came_from[(nr, nc)] = node
                heapq.heappush(open_heap, (tentative_g + h((nr, nc)), tentative_g, (nr, nc), node))
    return None


class Planner:
    def __init__(self, layers_dir: Path, plan_res: float):
        self.layers_dir = layers_dir
        cost_full, gt = load_raster(layers_dir / "cost.tif")
        # Source resolution from the geotransform (assume square pixels)
        self.src_res = abs(gt[1])
        factor = max(1, int(round(plan_res / self.src_res)))
        print(f"  source res {self.src_res:.3f} m, plan res {self.src_res*factor:.3f} m "
              f"({factor}x downsample) -> grid {cost_full.shape[0]//factor} x {cost_full.shape[1]//factor}")
        cost_plan = downsample(cost_full, factor)
        self.grid = Grid(cost=cost_plan, cell_size_m=self.src_res * factor,
                         h=cost_plan.shape[0], w=cost_plan.shape[1])
        self.factor = factor
        self.cost_full = cost_full

        # Display background
        hill_path = layers_dir / "hillshade.tif"
        if hill_path.exists():
            self.bg, _ = load_raster(hill_path)
            self.bg_label = "hillshade"
        else:
            self.bg = np.where(cost_full >= LETHAL_THRESHOLD, np.nan, cost_full)
            self.bg_label = "cost"

        self.start = None
        self.goal = None
        self.path = None

    def display_to_plan(self, x_pix, y_pix):
        """Map full-res display pixel to downsampled plan grid (row, col)."""
        return (int(y_pix // self.factor), int(x_pix // self.factor))

    def plan_to_display(self, r, c):
        return (c * self.factor + self.factor // 2, r * self.factor + self.factor // 2)

    def render(self):
        self.ax.clear()
        # Background
        self.ax.imshow(self.bg, cmap="gray", interpolation="nearest")
        # Cost overlay
        cost_show = np.where(self.cost_full >= LETHAL_THRESHOLD, np.nan, self.cost_full)
        self.ax.imshow(cost_show, cmap="turbo", alpha=0.35, interpolation="nearest",
                       norm=Normalize(vmin=np.nanpercentile(cost_show, 5),
                                      vmax=np.nanpercentile(cost_show, 95)))
        # Lethal cells dark
        lethal_show = np.where(self.cost_full >= LETHAL_THRESHOLD, 1.0, np.nan)
        self.ax.imshow(lethal_show, cmap="Greys", alpha=0.55, vmin=0, vmax=1,
                       interpolation="nearest")

        if self.start is not None:
            self.ax.scatter(self.start[0], self.start[1], c="lime", s=80,
                            edgecolors="black", zorder=5, label="start")
        if self.goal is not None:
            self.ax.scatter(self.goal[0], self.goal[1], c="red", s=80,
                            edgecolors="black", zorder=5, label="goal")
        if self.path is not None:
            xs = [self.plan_to_display(r, c)[0] for r, c in self.path]
            ys = [self.plan_to_display(r, c)[1] for r, c in self.path]
            self.ax.plot(xs, ys, "-", color="yellow", linewidth=2.5, zorder=4)

        self.ax.set_title(
            f"{self.layers_dir.name}  |  click: 1=start  2=goal  |  right-click: reset",
            fontsize=11,
        )
        self.ax.set_xlabel("col (display pixels)")
        self.ax.set_ylabel("row (display pixels)")
        self.fig.canvas.draw_idle()

    def on_click(self, event):
        if event.inaxes != self.ax:
            return
        if event.button == 3:  # right click resets
            self.start, self.goal, self.path = None, None, None
            self.render()
            return
        if event.xdata is None or event.ydata is None:
            return
        pt = (int(event.xdata), int(event.ydata))
        if self.start is None:
            self.start = pt
            print(f"  start = display{pt}  plan{self.display_to_plan(*pt)}")
            self.render()
        elif self.goal is None:
            self.goal = pt
            print(f"  goal  = display{pt}  plan{self.display_to_plan(*pt)}")
            self.render()
            self.run_planner()
        else:
            self.start = pt
            self.goal = None
            self.path = None
            print(f"  reset; new start = {pt}")
            self.render()

    def run_planner(self):
        s = self.display_to_plan(*self.start)
        g = self.display_to_plan(*self.goal)
        print(f"  running A* from {s} to {g} ...")
        path = astar(self.grid, s, g)
        if path is None:
            print("  no path found (either start/goal lethal or no connection)")
            return
        # Compute path length & cost
        length_m = (len(path) - 1) * self.grid.cell_size_m
        cell_costs = [self.grid.cost[r, c] for r, c in path]
        print(f"  path: {len(path)} cells, ~{length_m:.0f} m, "
              f"mean cell cost {np.mean(cell_costs):.3f}, "
              f"max cell cost {np.max(cell_costs):.3f}")
        self.path = path
        self.render()

    def go(self):
        self.fig, self.ax = plt.subplots(figsize=(12, 10))
        self.fig.canvas.mpl_connect("button_press_event", self.on_click)
        self.render()
        plt.show()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("layers_dir", type=Path)
    ap.add_argument("--plan-res", type=float, default=1.0,
                    help="Planner grid resolution in metres (downsamples for speed)")
    args = ap.parse_args()
    if not (args.layers_dir / "cost.tif").exists():
        sys.exit(f"cost.tif not found in {args.layers_dir} — run build_costmap.py first")
    p = Planner(args.layers_dir, args.plan_res)
    p.go()


if __name__ == "__main__":
    main()
