"""Fallback for /usr/bin/time on nodes that lack it (Hopper compute nodes, 2026-11-13).

Usage: python time_wrap.py <out_file> <command ...>. Writes one line "wall maxrss_kb user sys pct rc", the same fields as
`/usr/bin/time -f "%e %M %U %S %P %x"`, and exits with the command's exit code. Max RSS is the largest single child (ru_maxrss).
"""
import resource
import subprocess
import sys
import time

out, cmd = sys.argv[1], sys.argv[2:]
t0 = time.time()
rc = subprocess.call(cmd)
wall = time.time() - t0
ru = resource.getrusage(resource.RUSAGE_CHILDREN)
pct = f"{100 * (ru.ru_utime + ru.ru_stime) / wall:.0f}%" if wall > 0 else "0%"
with open(out, "w") as fh:
    fh.write(f"{wall:.2f} {ru.ru_maxrss} {ru.ru_utime:.2f} {ru.ru_stime:.2f} {pct} {rc}\n")
sys.exit(rc)
