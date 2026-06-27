import { RecordDossier, investigationContext, recordTypeLabel, type ParamGetter } from "@/components/record-dossier";
import type { EvidenceGraphResponse, RecordDetail } from "@/lib/api";

const API_BASE = process.env.POLARIS_API_BASE ?? "http://127.0.0.1:8077";

type PageSearchParams = Record<string, string | string[] | undefined>;

async function fetchJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} - ${path}`);
  return res.json() as Promise<T>;
}

function getterFor(searchParams: PageSearchParams): ParamGetter {
  return (key) => {
    const value = searchParams[key];
    if (Array.isArray(value)) return value[0] ?? null;
    return value ?? null;
  };
}

export default async function RecordDetailPage({
  params,
  searchParams,
}: {
  params: Promise<{ table: string; pk: string }> | { table: string; pk: string };
  searchParams?: Promise<PageSearchParams> | PageSearchParams;
}) {
  const { table, pk } = await params;
  const resolvedSearchParams = searchParams ? await searchParams : {};
  const context = investigationContext(getterFor(resolvedSearchParams));
  const detailPath = `/api/records/${encodeURIComponent(table)}/${encodeURIComponent(pk)}`;
  const graphPath = `/api/graph/record/${encodeURIComponent(table)}/${encodeURIComponent(pk)}`;

  let detail: RecordDetail;
  let graph: EvidenceGraphResponse | null = null;
  try {
    [detail, graph] = await Promise.all([
      fetchJson<RecordDetail>(detailPath),
      fetchJson<EvidenceGraphResponse>(graphPath).catch(() => null),
    ]);
  } catch (error) {
    return <Message tone="error">{String(error)}</Message>;
  }
  if (!detail) return <Message>Record not found.</Message>;

  const type = detail.record.type_label || recordTypeLabel(detail.record.record_type, detail.record.source, detail.table);

  return (
    <RecordDossier
      detail={detail}
      graph={graph}
      context={context}
      crumb={[{ label: "Records", href: "/records" }, { label: type }]}
    />
  );
}

function Message({ children, tone = "neutral" }: { children: React.ReactNode; tone?: "neutral" | "error" }) {
  return (
    <div className={`rounded border px-4 py-3 font-body-md text-body-md ${tone === "error" ? "border-error/30 bg-error/10 text-error" : "border-outline-variant bg-surface-container-low text-on-surface-variant"}`}>
      {children}
    </div>
  );
}
