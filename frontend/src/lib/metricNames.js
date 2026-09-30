import names from "./metric_names.json";

/**
 * Plain-English metric names and qualifiers, shared with the narrative table.
 *
 * metric_names.json is generated from LABEL_BY_PATH / QUALIFIER_BY_PATH in
 * backend/app/formatting.py (a backend test fails if it is stale), so a tile and
 * the table row for the same metric use the same base label and the same
 * qualifier wording. The tile shows the qualifier as small text beneath its value.
 *
 * Same lookup as the backend: the last two path segments, else the last one.
 */
function lookup(table, path) {
  const segs = String(path).split(".").filter(Boolean);
  for (const width of [2, 1]) {
    if (segs.length >= width) {
      const hit = table[segs.slice(-width).join(".")];
      if (hit) return hit;
    }
  }
  return null;
}

export const metricLabel = (path) => lookup(names.labels, path);
export const metricQualifier = (path) => lookup(names.qualifiers, path);

/** "latest month" -> "(latest month)": brackets, no comma before them, everywhere. */
export const bracketed = (qualifier) => (qualifier ? `(${qualifier})` : null);
