"use client";

import { use } from "react";
import type { ReactNode } from "react";
import { useSearchParams } from "next/navigation";
import { Card } from "@/components/nessus";
import { RecordDossier, investigationContext } from "@/components/record-dossier";
import { useApi } from "@/lib/use-api";
import type { EvidenceGraphResponse, RecordDetail } from "@/lib/api";

export default function MeetingDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const searchParams = useSearchParams();
  const context = investigationContext((key) => searchParams.get(key));
  const { data, loading, error } = useApi<RecordDetail>(`/api/records/lobbying/${encodeURIComponent(id)}`);
  const { data: graph } = useApi<EvidenceGraphResponse>(`/api/graph/record/lobbying/${encodeURIComponent(id)}`);

  if (loading) return <MeetingSkeleton />;
  if (error) return <Message tone="error">{error}</Message>;
  if (!data) return <Message>Meeting record not found.</Message>;

  // A meeting is a registered communication, not proof of influence — say so up
  // front, then let the shared dossier carry the analysis and connections.
  const lead = (
    <Card icon="handshake" title="Registered Communication">
      <div className="p-density-comfortable font-body-md text-body-md text-on-surface-variant leading-relaxed">
        This is a registered lobbying communication. It marks that contact occurred and supports an investigative path — it does not, on its own, prove policy influence or causation.
      </div>
    </Card>
  );

  return (
    <RecordDossier
      detail={data}
      graph={graph}
      context={context}
      crumb={[{ label: "Records", href: "/records" }, { label: "Meetings" }, { label: `MTG-${id}` }]}
      leadCard={lead}
    />
  );
}

function MeetingSkeleton() {
  return <div className="space-y-gutter">{[0, 1, 2, 3].map((i) => <div key={i} className="skeleton h-32" />)}</div>;
}

function Message({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "error" }) {
  return (
    <div className={`rounded border px-4 py-3 font-body-md text-body-md ${tone === "error" ? "border-error/30 bg-error/10 text-error" : "border-outline-variant bg-surface-container-low text-on-surface-variant"}`}>
      {children}
    </div>
  );
}
