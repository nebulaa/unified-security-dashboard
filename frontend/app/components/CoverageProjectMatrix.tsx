/**
 * Coverage by key project.
 *
 * Columns are fixed by the backend (`PROJECT_COLUMNS`), so every row is
 * comparable. The runtime column is one weighted cell across clusters and VMs;
 * its note carries both raw ratios so a large VM estate can't hide a missing
 * cluster.
 */
import { RAG_TEXT, formatPct } from "../lib/coverage";
import type { CoverageProject } from "../lib/types";

export default function CoverageProjectMatrix({
  projects,
  unmapped,
}: {
  projects: CoverageProject[];
  unmapped: { repos: number; cloud_accounts: number };
}) {
  if (projects.length === 0) return null;
  const columns = projects[0].cells;

  return (
    <div className="overflow-hidden rounded-lg border border-neutral-800/80">
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="bg-neutral-900/60 text-left text-xs font-medium text-neutral-500">
            <th className="px-4 py-3 font-medium">Project</th>
            {columns.map((cell) => (
              <th key={cell.metric} className="px-4 py-3 font-medium">
                {cell.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {projects.map((project) => (
            <tr key={project.key} className="border-t border-neutral-800/80">
              <td className="px-4 py-3 font-semibold text-neutral-100">
                {project.label}
                {project.flagship && (
                  <span className="ml-2 rounded bg-violet-500/15 px-1.5 py-0.5 align-middle text-[11px] font-semibold text-violet-700 dark:text-violet-300">
                    Flagship
                  </span>
                )}
              </td>
              {project.cells.map((cell) => (
                <td key={cell.metric} className="px-4 py-3">
                  <span
                    className={`text-base font-semibold tabular-nums ${RAG_TEXT[cell.rag]}`}
                  >
                    {cell.unavailable_sources.length > 0
                      ? "n/a"
                      : formatPct(cell.ratio.pct)}
                  </span>
                  <span className="ml-2 text-xs text-neutral-500">{cell.note}</span>
                </td>
              ))}
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr className="border-t border-neutral-800/80 bg-neutral-900/60">
            <td
              colSpan={columns.length + 1}
              className="px-4 py-3 text-xs text-neutral-500"
            >
              <p className="mt-2">
                {unmapped.repos} eligible repos
                {unmapped.cloud_accounts > 0
                  ? ` and ${unmapped.cloud_accounts} production accounts`
                  : ""}{" "}
                are not mapped to a key project — included in the figures above.
              </p>
            </td>
          </tr>
        </tfoot>
      </table>
    </div>
  );
}
