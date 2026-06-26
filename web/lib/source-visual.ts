/* Per-source visual identity — icon, accent colour, and a soft tint fill — so the
   record dossier reads by colour, not as a wall of grey text. One source category
   = one consistent colour everywhere (connection groups, the connection graph,
   the timeline dots, source chips). Colours are picked to sit on the light
   surface palette; the canonical record table name is the key.

   The map is keyed by the canonical SQL table/source name AND the common aliases
   the semantic and SQL layers use, so callers can pass either. */

export interface SourceVisual {
  icon: string;
  color: string; // accent (text / stroke / dot)
  soft: string; // soft background tint
}

const DEFAULT: SourceVisual = { icon: "dataset", color: "#64748b", soft: "#f1f5f9" };

const BY_KEY: Record<string, SourceVisual> = {
  contracts: { icon: "receipt_long", color: "#2563eb", soft: "#dbeafe" },
  grants: { icon: "payments", color: "#059669", soft: "#d1fae5" },
  donations: { icon: "volunteer_activism", color: "#dc2626", soft: "#fee2e2" },
  lobbying: { icon: "record_voice_over", color: "#d97706", soft: "#fef3c7" },
  lobbying_records: { icon: "record_voice_over", color: "#d97706", soft: "#fef3c7" },
  lobbying_communications: { icon: "record_voice_over", color: "#d97706", soft: "#fef3c7" },
  ocl_registrations: { icon: "assignment_ind", color: "#b45309", soft: "#fef3c7" },
  bills: { icon: "gavel", color: "#7c3aed", soft: "#ede9fe" },
  gazette: { icon: "menu_book", color: "#0891b2", soft: "#cffafe" },
  gazette_entries: { icon: "menu_book", color: "#0891b2", soft: "#cffafe" },
  tribunal: { icon: "balance", color: "#0d9488", soft: "#ccfbf1" },
  tribunal_decisions: { icon: "balance", color: "#0d9488", soft: "#ccfbf1" },
  appointments: { icon: "badge", color: "#4f46e5", soft: "#e0e7ff" },
  hansard_speeches: { icon: "forum", color: "#9333ea", soft: "#f3e8ff" },
  hansard_mentions: { icon: "forum", color: "#9333ea", soft: "#f3e8ff" },
  hansard_transcripts: { icon: "forum", color: "#9333ea", soft: "#f3e8ff" },
  politicians: { icon: "account_balance", color: "#041632", soft: "#d0e1fb" },
  source_records: { icon: "hub", color: "#64748b", soft: "#f1f5f9" },
  operations: { icon: "factory", color: "#64748b", soft: "#f1f5f9" },
  npri: { icon: "eco", color: "#65a30d", soft: "#ecfccb" },
  cer: { icon: "bolt", color: "#ca8a04", soft: "#fef9c3" },
  gc_news: { icon: "campaign", color: "#475569", soft: "#f1f5f9" },
  social_statements: { icon: "campaign", color: "#475569", soft: "#f1f5f9" },
};

// Group-label fallbacks (the connection groups arrive labelled, not keyed).
const BY_LABEL: Record<string, SourceVisual> = {
  "federal contracts": BY_KEY.contracts,
  "political donations": BY_KEY.donations,
  "grants & contributions": BY_KEY.grants,
  "lobbying communications": BY_KEY.lobbying,
  "lobbying registrations": BY_KEY.ocl_registrations,
  "bills & legislation": BY_KEY.bills,
  "canada gazette": BY_KEY.gazette,
  "tribunal decisions": BY_KEY.tribunal,
  "gic appointments": BY_KEY.appointments,
  "hansard transcripts": BY_KEY.hansard_speeches,
};

export function sourceVisual(key?: string | null, label?: string | null): SourceVisual {
  if (key) {
    const hit = BY_KEY[key.toLowerCase().trim()];
    if (hit) return hit;
  }
  if (label) {
    const hit = BY_LABEL[label.toLowerCase().trim()];
    if (hit) return hit;
  }
  return DEFAULT;
}
