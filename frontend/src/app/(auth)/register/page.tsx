import { connection } from "next/server";

import { RequestAccessForm } from "./request-access-form";
import { SelfServeRegisterForm } from "./self-serve-register-form";

// HRP-390: the register surface depends on the deployment mode. Self-hosted
// (onprem) installs get a real self-serve form posting to
// POST /api/auth/register; everything else keeps the moderated SaaS
// request-access funnel. DEPLOYMENT_MODE is a runtime env var on the
// frontend container (docker-compose.self-hosted.yml) — `connection()`
// keeps the page request-rendered so the build never bakes the mode in.
export default async function RegisterPage() {
  await connection();
  if (process.env.DEPLOYMENT_MODE === "onprem") {
    return <SelfServeRegisterForm />;
  }
  return <RequestAccessForm />;
}
