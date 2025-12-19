from typing import List, Tuple
import math

def solve_lap(cost: List[List[float]]) -> List[Tuple[int, int]]:
    try:
        import numpy as np
        from scipy.optimize import linear_sum_assignment
        cm = np.array(cost, dtype=float)
        rows, cols = linear_sum_assignment(cm)
        pairs = []
        for r, c in zip(rows, cols):
            val = cm[r, c]
            if math.isfinite(val) and val < 1e11:
                pairs.append((int(r), int(c)))
        return pairs
    except Exception:
        items = []
        for i, row in enumerate(cost):
            for j, val in enumerate(row):
                if math.isfinite(val) and val < 1e11:
                    items.append((val, i, j))
        items.sort(key=lambda x: x[0])
        used_i, used_j, pairs = set(), set(), []
        for val, i, j in items:
            if i in used_i or j in used_j:
                continue
            used_i.add(i); used_j.add(j)
            pairs.append((i, j))
        return pairs