import Link from "next/link";

export function AppVersion({ className, href }: { className?: string; href?: string }) {
  const version = process.env.NEXT_PUBLIC_APP_VERSION;
  if (!version) return null;
  if (href) {
    return <Link href={href} className={className}>v{version}</Link>;
  }
  return <span className={className}>v{version}</span>;
}
