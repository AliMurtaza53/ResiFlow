#!/bin/bash
#SBATCH --job-name=harvey_mask_depth
#SBATCH --partition=normal
# Mask Harvey 50 m cells deeper than 30 ft (9.144 m): permanent water and model-edge artifacts (owner GIS inspection 2026-11-12).
# The unmasked metre raster is kept as event_1_metres_unmasked.tif; event_1.tif (read by the pipeline) becomes the masked one.
# Same value as the new default in scripts/prepare_harvey_depths.py (--max-depth-m).
#SBATCH --time=00:30:00
#SBATCH --cpus-per-task=2
#SBATCH --mem=16G
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_harvey_mask_depth_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_harvey_mask_depth_%j.err
module purge
source /home/akothaw/miniforge/bin/activate /scratch/akothaw/conda_envs/nird
export PROJ_DATA=/scratch/akothaw/conda_envs/nird/lib/python3.10/site-packages/rasterio/proj_data
export PROJ_LIB=$PROJ_DATA
set -e
A=/scratch/akothaw/multimodal_hazard_data/soge_clusters/inputs/multihazard_aligned/flood_harvey_houston
[ -e $A/event_1_metres_unmasked.tif ] || mv $A/event_1.tif $A/event_1_metres_unmasked.tif
python - <<'PY'
import numpy as np, rasterio
A = "/scratch/akothaw/multimodal_hazard_data/soge_clusters/inputs/multihazard_aligned/flood_harvey_houston"
CAP = 30 * 0.3048
with rasterio.open(f"{A}/event_1_metres_unmasked.tif") as s:
    prof = s.profile; a = s.read(1); tags = s.tags()
b = a.copy()
with np.errstate(invalid="ignore"):
    over = np.isfinite(a) & (a > CAP)
b[over] = np.nan
prof.update(compress="deflate")
with rasterio.open(f"{A}/event_1.tif", "w", **prof) as d:
    d.write(b.astype("float32"), 1); d.update_tags(**tags, MAX_DEPTH_M=f"{CAP:.4f}", MASK_RULE="cells above 30 ft set to nodata (water bodies / edge artifacts)")
va, vb = np.isfinite(a), np.isfinite(b)
print(f"cap {CAP:.4f} m | valid before {va.sum():,} after {vb.sum():,} | masked {over.sum():,} ({over.sum()/va.sum():.2%})")
print("unchanged cells identical:", bool(np.array_equal(a[vb], b[vb])), "| masked only above cap:", bool((a[over] > CAP).all()), "| nothing else lost:", int((va & ~vb).sum()) == int(over.sum()))
v = b[vb].astype("float64")
print(f"NEW stats (m): min {v.min():.4f} p50 {np.percentile(v,50):.4f} p90 {np.percentile(v,90):.4f} p99 {np.percentile(v,99):.4f} max {v.max():.4f} mean {v.mean():.4f}")
print(f"share > 3 m {(v>3).mean():.2%} | > 6 m {(v>6).mean():.2%} | valid px {v.size:,}")
PY
ls -la $A
