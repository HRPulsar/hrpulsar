import type { Metadata, Viewport } from "next";
import { NextIntlClientProvider } from "next-intl";
import { getLocale } from "next-intl/server";
import { Geist, Geist_Mono, Inter } from "next/font/google";
import { Toaster } from "@/components/ui/sonner";
import { ThemeProvider } from "@/components/theme-provider";
import { RuntimeEnvScript } from "@/components/runtime-env-script";
import { BrandStyle } from "@/components/brand-style";
import { DEFAULT_BRAND_NAME, getBrandName, getFaviconUrl } from "@/lib/brand";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

// Cyrillic fallback for enterprise locales (ru): Geist ships no Cyrillic
// glyphs. Subset-only face with a Cyrillic unicode-range — browsers fetch
// it lazily, only when Cyrillic text actually renders, so Latin-only
// deployments pay nothing beyond the @font-face declaration (hence no
// preload). Wired after Geist in --font-sans/--font-heading (globals.css).
const interCyrillic = Inter({
  variable: "--font-cyrillic-sans",
  subsets: ["cyrillic"],
  preload: false,
});

// generateMetadata instead of a static export so a white-label brand
// (HRP-393) picked up from the runtime container env lands in the
// document metadata — the layout is already request-dynamic via
// RuntimeEnvScript, so this re-evaluates against the live env.
export async function generateMetadata(): Promise<Metadata> {
  const brand = getBrandName();
  const stock = brand === DEFAULT_BRAND_NAME;
  const title = stock ? "HRPulsar — Open Source Talent Management Platform" : brand;
  const ogDescription = stock
    ? "Manage competencies, run 360° assessments, build development plans. Self-host with Docker or use the cloud."
    : "Talent management platform.";
  const favicon = getFaviconUrl();
  return {
    title: {
      default: title,
      template: `%s | ${brand}`,
    },
    description: stock
      ? "Self-hostable platform for competency management, 360° assessments, development plans, and employee growth tracking. Open source, AGPLv3."
      : "Talent management platform.",
    metadataBase: stock ? new URL("https://hrpulsar.com") : undefined,
    icons: {
      icon: [
        favicon.split("?")[0].endsWith(".svg")
          ? { url: favicon, type: "image/svg+xml" }
          : { url: favicon },
      ],
      apple: [{ url: "/apple-touch-icon.png", sizes: "180x180" }],
    },
    manifest: "/site.webmanifest",
    // A custom brand drops the stock og-image and canonical URL instead of
    // inheriting HRPulsar artwork (and without metadataBase a relative image
    // would resolve to a broken localhost URL).
    openGraph: {
      type: "website",
      siteName: brand,
      title,
      description: ogDescription,
      url: stock ? "https://hrpulsar.com" : undefined,
      locale: "en_US",
      images: stock
        ? [{ url: "/og-image.png", width: 1200, height: 630, alt: brand }]
        : undefined,
    },
    twitter: {
      card: "summary_large_image",
      title,
      description: ogDescription,
      images: stock ? ["/og-image.png"] : undefined,
    },
    // The product frontend is never indexable — the public site lives in the
    // standalone marketing/ app (HRP-389). app/robots.ts mirrors this.
    robots: { index: false, follow: false },
  };
}

export const viewport: Viewport = {
  themeColor: "#ffffff",
};

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  // i18n (F1): resolved per request from the NEXT_LOCALE cookie /
  // Accept-Language by src/i18n/request.ts. The tree is already
  // request-dynamic (RuntimeEnvScript calls headers()), so this adds no
  // static-rendering cost.
  const locale = await getLocale();
  return (
    <html
      lang={locale}
      className={`${geistSans.variable} ${geistMono.variable} ${interCyrillic.variable} h-full antialiased`}
      suppressHydrationWarning
    >
      <head>
        <RuntimeEnvScript />
        <BrandStyle />
      </head>
      <body className="h-full bg-background text-foreground">
        {/* Messages and locale are inherited from the server request
            config (next-intl v4). */}
        <NextIntlClientProvider>
          <ThemeProvider>
            {children}
            <Toaster />
          </ThemeProvider>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
