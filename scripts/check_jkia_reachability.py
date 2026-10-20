"""
ACDOS — Rising & Campbell (2017) grid: JKIA reachability check
Run against the full nairobi-driving-extended/ folder to determine, for every
origin point in the dataset, whether the destination cell nearest JKIA
resolves to a real driving time or 'inf' (unroutable).

Usage:
    python3 check_jkia_reachability.py /path/to/nairobi-driving-extended

Outputs:
    jkia_reachability.csv  — one row per origin file found
    Summary printed to stdout
"""
import sys, os, re, math, csv

# --- Grid parameters, from tools_map.R setup.driving(), use.expanded.grid = TRUE ---
MINLON, MAXLON = 36.65, 37.176427
MINLAT, MAXLAT = -1.45, -1.15
BIGSTEP = 0.01
RADIUS, CELLS = 0.4, 100
SMALLSTEP = 2 * RADIUS / CELLS  # 0.008

# JKIA approx terminal coordinates — adjust if you have a more precise figure
JKIA_LAT, JKIA_LON = -1.3192, 36.9278

FALLBACK_SEARCH_CELLS = 20  # ~ +/-17.6km search radius if exact cell is inf


def origin_center(index, dlon=BIGSTEP, dlat=BIGSTEP):
    """Row-major count from (MAXLAT, MINLON), matches tools_map.R get.center()."""
    lat, idx = MAXLAT, index
    while lat > MINLAT:
        lon = MINLON
        while lon < MAXLON:
            idx -= 1
            if idx == 0:
                return (lat, lon)
            lon += dlon
        lat -= dlat
    return None


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dlmb = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def load_grid(path):
    with open(path) as f:
        return [l.strip().rstrip(",").split(",") for l in f if l.strip()]


def nearest_valid(rows, row_i, col_j, max_search=FALLBACK_SEARCH_CELLS):
    n, m = len(rows), len(rows[0]) if rows else 0
    best = None
    for r in range(max(0, row_i - max_search), min(n, row_i + max_search + 1)):
        for c in range(max(0, col_j - max_search), min(m, col_j + max_search + 1)):
            v = rows[r][c].strip()
            if v not in ("inf", "nan", ""):
                d = ((r - row_i) ** 2 + (c - col_j) ** 2) ** 0.5
                if best is None or d < best[0]:
                    best = (d, r, c, float(v))
    return best


def main(folder):
    pattern = re.compile(r"driving-(\d+)\.csv$")
    files = sorted(
        (f for f in os.listdir(folder) if pattern.search(f)),
        key=lambda f: int(pattern.search(f).group(1)),
    )
    if not files:
        print(f"No driving-###.csv files found in {folder}")
        return

    out_rows = []
    n_exact_valid = n_fallback_valid = n_unreachable = 0

    for fname in files:
        idx = int(pattern.search(fname).group(1))
        center = origin_center(idx)
        if center is None:
            continue
        clat, clon = center
        straight_km = haversine_km(clat, clon, JKIA_LAT, JKIA_LON)

        rows = load_grid(os.path.join(folder, fname))
        win_maxlat = clat + RADIUS
        win_minlon = clon - RADIUS
        row_i = round((win_maxlat - JKIA_LAT) / SMALLSTEP)
        col_j = round((JKIA_LON - win_minlon) / SMALLSTEP)

        exact_val = None
        if 0 <= row_i < len(rows) and rows and 0 <= col_j < len(rows[0]):
            v = rows[row_i][col_j].strip()
            if v not in ("inf", "nan", ""):
                exact_val = float(v)

        fallback_val = fallback_km = None
        if exact_val is None:
            b = nearest_valid(rows, row_i, col_j)
            if b:
                d_cells, r, c, val = b
                fallback_val = val
                fallback_km = d_cells * SMALLSTEP * 111.0

        if exact_val is not None:
            n_exact_valid += 1
        elif fallback_val is not None:
            n_fallback_valid += 1
        else:
            n_unreachable += 1

        out_rows.append({
            "origin_index": idx,
            "origin_lat": round(clat, 5),
            "origin_lon": round(clon, 5),
            "straight_line_km_to_jkia": round(straight_km, 2),
            "exact_cell_sec": exact_val,
            "exact_cell_min": round(exact_val / 60, 1) if exact_val else None,
            "fallback_valid_sec": fallback_val,
            "fallback_offset_km": round(fallback_km, 2) if fallback_km else None,
        })

    with open("jkia_reachability.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
        w.writeheader()
        w.writerows(out_rows)

    total = len(out_rows)
    print(f"Origins processed: {total}")
    print(f"  Exact JKIA-adjacent cell valid: {n_exact_valid} ({100*n_exact_valid/total:.1f}%)")
    print(f"  Valid only via fallback search: {n_fallback_valid} ({100*n_fallback_valid/total:.1f}%)")
    print(f"  Unreachable within {FALLBACK_SEARCH_CELLS} cells: {n_unreachable} ({100*n_unreachable/total:.1f}%)")
    print("Wrote jkia_reachability.csv")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 check_jkia_reachability.py /path/to/nairobi-driving-extended")
        sys.exit(1)
    main(sys.argv[1])
