import { redirect } from "next/navigation";
import { serverFetch } from "./lib/api/server";
import type { Me } from "./lib/types";

// Single landing rule: admins go to /admin (their triage hub), everyone
// else to /executive. From either landing they can navigate freely to any
// page.
export default async function Index() {
  const me = await serverFetch<Me>("/me");
  redirect(me.is_admin ? "/admin" : "/executive");
}
