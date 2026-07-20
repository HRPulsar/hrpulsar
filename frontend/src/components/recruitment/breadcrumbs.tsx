"use client";

import * as React from "react";
import Link from "next/link";
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";

export interface BreadcrumbSegment {
  label: string;
  href?: string;
}

interface RecruitmentBreadcrumbsProps {
  segments: BreadcrumbSegment[];
}

function truncateLabel(label: string, max = 40): string {
  if (label.length <= max) return label;
  return label.slice(0, max) + "...";
}

export function RecruitmentBreadcrumbs({ segments }: RecruitmentBreadcrumbsProps) {
  const allSegments: BreadcrumbSegment[] = [
    { label: "Recruitment", href: "/recruitment" },
    ...segments,
  ];

  return (
    <Breadcrumb data-testid="recruitment-breadcrumbs">
      <BreadcrumbList>
        {allSegments.map((segment, index) => {
          const isLast = index === allSegments.length - 1;
          const truncated = truncateLabel(segment.label);
          const needsTooltip = truncated !== segment.label;

          return (
            <React.Fragment key={index}>
              {index > 0 && <BreadcrumbSeparator />}
              <BreadcrumbItem>
                {isLast ? (
                  <BreadcrumbPage title={needsTooltip ? segment.label : undefined}>
                    {truncated}
                  </BreadcrumbPage>
                ) : segment.href ? (
                  <Link href={segment.href} className="transition-colors hover:text-foreground" title={needsTooltip ? segment.label : undefined}>
                    {truncated}
                  </Link>
                ) : (
                  <BreadcrumbPage title={needsTooltip ? segment.label : undefined}>
                    {truncated}
                  </BreadcrumbPage>
                )}
              </BreadcrumbItem>
            </React.Fragment>
          );
        })}
      </BreadcrumbList>
    </Breadcrumb>
  );
}
