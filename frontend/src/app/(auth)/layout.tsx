import type { Viewport } from "next";

import { AppVersion } from "@/components/app-version";

export const viewport: Viewport = {
  themeColor: "#060a14",
};

export default function AuthLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="relative flex min-h-screen flex-col items-center justify-center px-4 py-12 overflow-hidden bg-[#060a14]">
      <div
        className="pointer-events-none absolute inset-0 opacity-70"
        style={{
          backgroundImage:
            "radial-gradient(1.2px 1.2px at 20px 30px, rgba(255,255,255,0.5), transparent)," +
            "radial-gradient(1px 1px at 80px 60px, rgba(255,255,255,0.4), transparent)," +
            "radial-gradient(0.8px 0.8px at 150px 20px, rgba(255,255,255,0.3), transparent)," +
            "radial-gradient(1px 1px at 40px 120px, rgba(255,255,255,0.4), transparent)," +
            "radial-gradient(0.6px 0.6px at 110px 90px, rgba(255,255,255,0.3), transparent)," +
            "radial-gradient(1.5px 1.5px at 170px 140px, rgba(255,255,255,0.5), transparent)," +
            "radial-gradient(0.8px 0.8px at 60px 160px, rgba(255,255,255,0.35), transparent)",
          backgroundSize: "200px 180px",
        }}
      />
      <div
        className="pointer-events-none absolute inset-0 opacity-50"
        style={{
          backgroundImage:
            "radial-gradient(0.8px 0.8px at 35px 45px, rgba(255,255,255,0.4), transparent)," +
            "radial-gradient(1px 1px at 95px 15px, rgba(255,255,255,0.35), transparent)," +
            "radial-gradient(0.6px 0.6px at 140px 80px, rgba(255,255,255,0.3), transparent)," +
            "radial-gradient(1.2px 1.2px at 10px 110px, rgba(255,255,255,0.45), transparent)," +
            "radial-gradient(0.7px 0.7px at 120px 55px, rgba(255,255,255,0.3), transparent)",
          backgroundSize: "170px 150px",
        }}
      />
      <div
        className="pointer-events-none absolute inset-0"
        style={{
          backgroundImage:
            "radial-gradient(500px 500px at 50% 40%, rgba(30,70,180,0.06), transparent)",
        }}
      />
      <div className="relative z-10">{children}</div>
      <div className="absolute bottom-4 left-0 right-0 text-center">
        <AppVersion className="text-[11px] text-white/20" />
      </div>
    </div>
  );
}
