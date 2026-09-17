import { redirect } from "next/navigation";
import { developerNavQueryString, toScalar } from "../_shared";

/** Legacy `/developer/wiz` → Explore findings with Wiz source filter. */
export default async function DeveloperWizRedirect(props: {
  searchParams: Promise<Record<string, string | string[]>>;
}) {
  const sp = await props.searchParams;
  const params = new URLSearchParams(
    developerNavQueryString(sp).replace(/^\?/, ""),
  );
  if (!toScalar(sp.source)) params.set("source", "wiz");
  const qs = params.toString();
  redirect(qs ? `/developer/findings?${qs}` : "/developer/findings?source=wiz");
}
