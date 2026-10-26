"""CoACD in its own process, so a slow or crashing decomposition never takes the backend with it.

    python -m pai_agent.simready.decompose <in.npz> <out.npz> <threshold> <max_parts> <seed>

`in.npz` holds `vertices` (n x 3, metres) and `faces` (m x 3); `out.npz` gets `count` and per
convex part `v<i>` and `f<i>`. convert.py starts it with a time limit and reads the result.
"""

from __future__ import annotations

import sys

import numpy as np


def main(argv: list[str]) -> int:
    source, target, threshold, max_parts, seed = argv[0], argv[1], float(argv[2]), int(argv[3]), int(argv[4])
    import coacd

    coacd.set_log_level("error")
    with np.load(source) as data:
        mesh = coacd.Mesh(np.asarray(data["vertices"], dtype=np.float64), np.asarray(data["faces"], dtype=np.int32))
    parts = coacd.run_coacd(mesh, threshold=threshold, max_convex_hull=max_parts, seed=seed)
    arrays = {"count": np.array(len(parts))}
    for index, (vertices, faces) in enumerate(parts):
        arrays[f"v{index}"] = np.asarray(vertices, dtype=np.float64)
        arrays[f"f{index}"] = np.asarray(faces, dtype=np.int32)
    with open(target, "wb") as handle:
        np.savez(handle, **arrays)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
