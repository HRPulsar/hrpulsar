/* eslint-disable react/jsx-no-literals -- accepted F2 debt (HRP-476): public
   unauthenticated company profile, deliberately English until localized */
"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { api, ApiError } from "@/lib/api";
import { getLandingHref } from "@/lib/landing-url";
import { getBrandName } from "@/lib/brand";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";

interface ActivityField {
  id: string;
  activity_field_id: string;
  title: string;
  tenant_id: string;
  created_at: string;
}

interface PublicCompany {
  name: string;
  slug: string;
  industry: string | null;
  company_size: string | null;
  website: string | null;
  description: string | null;
  activity_fields: ActivityField[];
  division_count: number;
  employee_count: number;
}

export default function PublicCompanyPage() {
  const params = useParams<{ slug: string }>();
  const [company, setCompany] = useState<PublicCompany | null>(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);

  useEffect(() => {
    if (!params.slug) return;

    api
      .get<PublicCompany>(`/public/company/${params.slug}`)
      .then(setCompany)
      .catch((err) => {
        if (err instanceof ApiError && err.status === 404) {
          setNotFound(true);
        }
      })
      .finally(() => setLoading(false));
  }, [params.slug]);

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background text-muted-foreground">
        Loading...
      </div>
    );
  }

  if (notFound || !company) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center bg-background">
        <h1 className="text-4xl font-bold tracking-tight">404</h1>
        <p className="mt-2 text-muted-foreground">Company not found</p>
        <Link
          href={getLandingHref()}
          className="mt-6 text-sm font-medium text-brand hover:underline"
        >
          Back to home
        </Link>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="border-b">
        <div className="mx-auto flex h-14 max-w-3xl items-center px-6">
          <Link href={getLandingHref()} className="text-sm font-semibold tracking-tight">
            {getBrandName()}
          </Link>
        </div>
      </header>

      <main className="mx-auto max-w-3xl px-6 py-10">
        {/* Company name + badges */}
        <div className="space-y-3">
          <h1 className="text-3xl font-bold tracking-tight">{company.name}</h1>
          <div className="flex flex-wrap items-center gap-2">
            {company.industry && (
              <Badge variant="secondary">{company.industry}</Badge>
            )}
            {company.company_size && (
              <Badge variant="outline">{company.company_size}</Badge>
            )}
          </div>
        </div>

        {/* Website */}
        {company.website && (
          <a
            href={
              company.website.startsWith("http")
                ? company.website
                : `https://${company.website}`
            }
            target="_blank"
            rel="noopener noreferrer"
            className="mt-4 inline-flex items-center gap-1.5 text-sm text-brand hover:underline"
          >
            <svg
              className="h-4 w-4"
              fill="none"
              viewBox="0 0 24 24"
              strokeWidth={1.5}
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M12 21a9.004 9.004 0 0 0 8.716-6.747M12 21a9.004 9.004 0 0 1-8.716-6.747M12 21c2.485 0 4.5-4.03 4.5-9S14.485 3 12 3m0 18c-2.485 0-4.5-4.03-4.5-9S9.515 3 12 3m0 0a8.997 8.997 0 0 1 7.843 4.582M12 3a8.997 8.997 0 0 0-7.843 4.582m15.686 0A11.953 11.953 0 0 1 12 10.5c-2.998 0-5.74-1.1-7.843-2.918m15.686 0A8.959 8.959 0 0 1 21 12c0 .778-.099 1.533-.284 2.253m0 0A17.919 17.919 0 0 1 12 16.5a17.92 17.92 0 0 1-8.716-2.247m0 0A8.966 8.966 0 0 1 3 12c0-1.264.26-2.467.732-3.558"
              />
            </svg>
            {company.website.replace(/^https?:\/\//, "")}
          </a>
        )}

        {/* Description */}
        {company.description && (
          <p className="mt-6 leading-relaxed text-muted-foreground">
            {company.description}
          </p>
        )}

        {/* Stats */}
        <div className="mt-8 grid grid-cols-2 gap-4">
          <Card>
            <CardContent className="pt-1">
              <p className="text-2xl font-bold">{company.division_count}</p>
              <p className="text-sm text-muted-foreground">Divisions</p>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-1">
              <p className="text-2xl font-bold">{company.employee_count}</p>
              <p className="text-sm text-muted-foreground">Employees</p>
            </CardContent>
          </Card>
        </div>

        {/* Activity fields */}
        {company.activity_fields.length > 0 && (
          <div className="mt-8">
            <h2 className="text-sm font-medium text-muted-foreground">
              Activity fields
            </h2>
            <div className="mt-2 flex flex-wrap gap-2">
              {company.activity_fields.map((field) => (
                <Badge key={field.id} variant="secondary">
                  {field.title}
                </Badge>
              ))}
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
