/** Merge query params onto a path, preserving any params already on `basePath`. */
export function mergeQueryHref(
  basePath: string,
  extra: Record<string, string | undefined>,
): string {
  const q = basePath.indexOf("?");
  const path = q >= 0 ? basePath.slice(0, q) : basePath;
  const params = new URLSearchParams(q >= 0 ? basePath.slice(q + 1) : "");
  for (const [key, value] of Object.entries(extra)) {
    if (value != null && value !== "") {
      params.set(key, value);
    }
  }
  const qs = params.toString();
  return qs ? `${path}?${qs}` : path;
}
