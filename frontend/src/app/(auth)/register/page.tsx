import { connection } from "next/server";

import { RequestAccessForm } from "./request-access-form";
import { SelfServeRegisterForm } from "./self-serve-register-form";

// HRP-390: the register surface depends on the deployment mode. Self-hosted
// (onprem) installs get a real self-serve form posting to
// POST /api/auth/register; everything else keeps the moderated SaaS
// request-access funnel. DEPLOYMENT_MODE is a runtime env var on the
// frontend container (docker-compose.self-hosted.yml) — `connection()`
// keeps the page request-rendered so the build never bakes the mode in.
export default async function RegisterPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  await connection();
  // HRP-927: "move to HRPulsar" of the public check brings the address its
  // checks are saved with - they follow an account of that email.
  const email = (await searchParams).email;
  const defaultEmail = typeof email === "string" ? email.slice(0, 320) : "";
  if (process.env.DEPLOYMENT_MODE === "onprem") {
    return <SelfServeRegisterForm defaultEmail={defaultEmail} />;
  }
  return <RequestAccessForm defaultEmail={defaultEmail} />;
}
