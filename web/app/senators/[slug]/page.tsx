"use client";

import { use } from "react";
import { PlannedPoliticalProfile } from "@/components/planned-political-profile";

export default function SenatorProfile({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = use(params);
  return <PlannedPoliticalProfile kind="senator" slug={slug} />;
}
