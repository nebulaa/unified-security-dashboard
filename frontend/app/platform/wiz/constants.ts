/** Platform /platform/wiz category tabs — keep in sync with WIZ_CATEGORY_LABELS (backend). */
export const PLATFORM_WIZ_CATEGORY_TABS = [
  { id: "issue", label: "Wiz issues" },
  { id: "cloud_config", label: "Cloud misconfigs" },
  { id: "vulnerability", label: "CISA KEV CVEs" },
] as const;

export type PlatformWizCategoryTab =
  (typeof PLATFORM_WIZ_CATEGORY_TABS)[number]["id"];

export const DEFAULT_PLATFORM_WIZ_CATEGORY: PlatformWizCategoryTab = "issue";

const PLATFORM_WIZ_CATEGORY_IDS = new Set<string>(
  PLATFORM_WIZ_CATEGORY_TABS.map((t) => t.id),
);

export function parsePlatformWizCategoryParam(
  value: string | undefined,
): PlatformWizCategoryTab {
  if (value && PLATFORM_WIZ_CATEGORY_IDS.has(value)) {
    return value as PlatformWizCategoryTab;
  }
  return DEFAULT_PLATFORM_WIZ_CATEGORY;
}

export function isCanonicalPlatformWizCategoryParam(
  value: string | undefined,
): value is PlatformWizCategoryTab {
  return !!value && PLATFORM_WIZ_CATEGORY_IDS.has(value);
}
