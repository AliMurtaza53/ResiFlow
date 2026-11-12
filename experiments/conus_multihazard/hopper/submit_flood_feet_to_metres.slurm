#!/bin/bash
#SBATCH --job-name=flood_feet_to_m
#SBATCH --partition=normal
# Harvey and Sandy aligned flood-depth rasters were written in FEET but labelled and consumed as metres (confirmed 2026-11-12).
# This job produces metre versions WITHOUT touching the old files' data: each old event_1.tif is renamed to
# event_1_feet_unconverted.tif (a rename, no rewrite; other hard links to the old inode are unaffected) and a NEW event_1.tif is written.
#  - Harvey: aligned file x 0.3048 via the existing align_hazard_rasters.py --unit-scale (same grid, nearest). Exact, because the
#    50 m raster was made with Resampling.average (linear), so scaling after averaging equals averaging after scaling.
#  - Sandy: re-run the patched prepare_sandy_depths.py (default --unit-scale 0.3048) and cross-check it against old x 0.3048.
# Both results are checked against the old files (grid, CRS, nodata mask, ratio) and written to results/flood_rescale_check.txt.
#SBATCH --time=01:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=48G
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_flood_feet_to_m_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_flood_feet_to_m_%j.err
#SBATCH --exclude=hop059

module purge
source /home/akothaw/miniforge/bin/activate /scratch/akothaw/conda_envs/nird
# Nov 2026 env rebuild: conda PROJ db (layout 1.5) vs pip rasterio (needs >= 1.6). Use rasterio's bundled db.
export PROJ_DATA=/scratch/akothaw/conda_envs/nird/lib/python3.10/site-packages/rasterio/proj_data
export PROJ_LIB=$PROJ_DATA
set -e

DATA=/scratch/akothaw/multimodal_hazard_data
ALIGNED=$DATA/soge_clusters/inputs/multihazard_aligned
REPO=$DATA/code/ResiFlow_dump
PATCHED=$DATA/stage2_scripts/prep_patched
export PYTHONPATH=$REPO/src:$PYTHONPATH
BK=event_1_feet_unconverted.tif

for h in flood_harvey_houston flood_sandy_northeast; do
  [ -e "$ALIGNED/$h/$BK" ] || mv "$ALIGNED/$h/event_1.tif" "$ALIGNED/$h/$BK"
  ls -la "$ALIGNED/$h"
done

echo "== Harvey: old x 0.3048"
python "$REPO/scripts/align_hazard_rasters.py" \
  --input "$ALIGNED/flood_harvey_houston/$BK" \
  --reference "$ALIGNED/flood_harvey_houston/$BK" \
  --nearest --unit-scale 0.3048 \
  --output "$ALIGNED/flood_harvey_houston/event_1.tif"

echo "== Sandy: patched prep (feet -> metres)"
python "$PATCHED/prepare_sandy_depths.py" \
  --raw-dir "$DATA/inputs_raw/flood" \
  --output "$ALIGNED/flood_sandy_northeast/event_1.tif" \
  --resolution 50 --unit-scale 0.3048

echo "== verification"
python - <<'PY' | tee "$DATA/results/flood_rescale_check.txt"
import numpy as np, rasterio
A="/scratch/akothaw/multimodal_hazard_data/soge_clusters/inputs/multihazard_aligned"
for h in ("flood_harvey_houston","flood_sandy_northeast"):
    with rasterio.open(f"{A}/{h}/event_1_feet_unconverted.tif") as o, rasterio.open(f"{A}/{h}/event_1.tif") as n:
        print(f"== {h}")
        print(" grid equal:", o.transform==n.transform and o.shape==n.shape, "| crs equal:", o.crs==n.crs, "| nodata old/new:", o.nodata, n.nodata, "| dtype", o.dtypes[0], n.dtypes[0])
        a=o.read(1).astype("float64"); b=n.read(1).astype("float64")
        va=np.isfinite(a); vb=np.isfinite(b)
        print(" valid px old/new:", int(va.sum()), int(vb.sum()), "| masks identical:", bool((va==vb).all()), "| px only in old:", int((va&~vb).sum()), "only in new:", int((vb&~va).sum()))
        m=va&vb
        r=b[m]/np.maximum(a[m],1e-12)
        print(f" ratio new/old on shared valid px: min {r.min():.6f} max {r.max():.6f} (expect 0.304800)")
        print(f" max |new - old*0.3048| = {np.abs(b[m]-a[m]*0.3048).max():.3e}")
        v=b[vb]
        print(f" NEW depth (m): min {v.min():.4f} p50 {np.percentile(v,50):.4f} p90 {np.percentile(v,90):.4f} p99 {np.percentile(v,99):.4f} max {v.max():.4f}")
        print(f" share > 3 m {(v>3).mean():.3%} | > 6 m {(v>6).mean():.3%} | > 9 m {(v>9).mean():.3%}")
        v0=a[va]; print(f" OLD (feet) : p50 {np.percentile(v0,50):.4f} max {v0.max():.4f}")
PY
echo "== done"
