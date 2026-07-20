import type { NextConfig } from "next";
import { withSentryConfig } from "@sentry/nextjs";
import * as fs from "fs";
import * as path from "path";

// Load monorepo-root .env for server-side env vars (blog CMS credentials, etc.).
// Next.js only auto-loads .env files next to next.config; the project keeps
// secrets in the repo-root .env. Existing process.env wins over file values.
try {
  const rootEnv = fs.readFileSync(path.resolve(process.cwd(), "../.env"), "utf-8");
  for (const rawLine of rootEnv.split("\n")) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) continue;
    const eq = line.indexOf("=");
    if (eq < 0) continue;
    const key = line.slice(0, eq).trim();
    if (!key || key in process.env) continue;
    let value = line.slice(eq + 1).trim();
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
      value = value.slice(1, -1);
    }
    process.env[key] = value;
  }
} catch {}

// App version: prefer env var (Docker build arg), fallback to version.py, then "dev"
let APP_VERSION = process.env.APP_VERSION || "dev";
if (APP_VERSION === "dev") {
  try {
    const content = fs.readFileSync(
      path.resolve(process.cwd(), "../version.py"),
      "utf-8",
    );
    const match = content.match(/__version__\s*=\s*"([^"]+)"/);
    if (match) APP_VERSION = match[1];
  } catch {}
}

const nextConfig: NextConfig = {
  env: {
    NEXT_PUBLIC_APP_VERSION: APP_VERSION,
  },
  output: "standalone",
};

// Wrap with Sentry only when DSN is configured
const hasSentry = !!process.env.NEXT_PUBLIC_SENTRY_DSN;

export default hasSentry
  ? withSentryConfig(nextConfig, {
      // Upload source maps for better stack traces
      sourcemaps: {
        deleteSourcemapsAfterUpload: true,
      },
      // Suppress Sentry CLI logs in dev
      silent: true,
    })
  : nextConfig;
