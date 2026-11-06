"""Minimum-distance rule between machines of the same type."""
from __future__ import annotations

import math


def distance(r1, r2, measure="edge"):
    """r = (x, y, w, h). edge: empty tiles between the footprints (max of x/y gap);
    center: euclidean distance between centres."""
    x1, y1, w1, h1 = r1
    x2, y2, w2, h2 = r2
    if measure == "center":
        return math.hypot((x1 + w1 / 2) - (x2 + w2 / 2), (y1 + h1 / 2) - (y2 + h2 / 2))
    gx = max(0, x2 - (x1 + w1), x1 - (x2 + w2))
    gy = max(0, y2 - (y1 + h1), y1 - (y2 + h2))
    return max(gx, gy)


def violations(rects, measure="edge"):
    """rects: list of (key, (x, y, w, h), min_dist). Returns [(key1, key2, dist, required)]."""
    out = []
    for i in range(len(rects)):
        k1, r1, d1 = rects[i]
        for j in range(i + 1, len(rects)):
            k2, r2, d2 = rects[j]
            if k1[0] != k2[0]:
                continue  # rule applies between machines of the same type only
            dist = distance(r1, r2, measure)
            if dist < d1 - 1e-9:
                out.append((k1, k2, dist, d1))
    return out
