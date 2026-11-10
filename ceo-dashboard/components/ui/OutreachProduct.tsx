// Product identity for the Outreach lanes (Kelvin, 2026-11-09: "I can't tell
// what is what"). One badge, one colour per product, used by every lane so a
// Cloud Decoded card and a consulting card never look alike.
//
// Colours come from the CEO Decoded status palette, each product owning one:
// blue for Cloud Decoded (the SaaS), amber for consulting, mint for partners.

export type ProductKey = "cloud_decoded" | "consulting" | "partners" | "other";

export type CompanyConflict = {
  product_id: string | null;
  product: string | null;
  lead_id: string | null;
  sequence_id: string | null;
  status: string | null;
  committed: boolean;
};

const PRODUCTS: Record<ProductKey, { label: string; color: string }> = {
  cloud_decoded: { label: "CLOUD DECODED", color: "#7ea6f5" },
  consulting: { label: "CONSULTING", color: "#e8963f" },
  partners: { label: "PARTNER", color: "#5eead4" },
  other: { label: "OTHER", color: "#9aa2ab" },
};

// Keyed on the product NAME the API returns ("Cloud Decoded",
// "THD Agentic Systems Consulting", "Referral Partners").
export function productKey(name: string | null | undefined): ProductKey {
  const n = (name ?? "").toLowerCase();
  if (n.includes("cloud decoded")) return "cloud_decoded";
  if (n.includes("consulting")) return "consulting";
  if (n.includes("partner")) return "partners";
  return "other";
}

export function productLabel(name: string | null | undefined): string {
  const key = productKey(name);
  return key === "other" ? (name ?? "UNKNOWN PRODUCT").toUpperCase() : PRODUCTS[key].label;
}

export function ProductBadge({ name }: { name: string | null | undefined }) {
  const { color } = PRODUCTS[productKey(name)];
  return (
    <span
      className="px-2 py-0.5 rounded-[5px] text-[10.5px] font-mono font-bold tracking-wide shrink-0"
      style={{ background: `${color}22`, color, border: `1px solid ${color}55` }}
      title={name ?? undefined}
    >
      {productLabel(name)}
    </span>
  );
}

// Left-border colour for a card, so the product reads before any text does.
export function productColor(name: string | null | undefined): string {
  return PRODUCTS[productKey(name)].color;
}

const STATUS_TEXT: Record<string, string> = {
  awaiting_buyer: "in Find the Buyer",
  pending_hitl: "draft awaiting approval",
  approved_hitl: "approved, email queued",
  approved_manual: "approved, ready to paste",
};

function describe(c: CompanyConflict): string {
  const s = c.status ?? "";
  return STATUS_TEXT[s] ?? s.replace(/_/g, " ");
}

// The warning shown when the same company has a card under another product.
// `blocking` comes from the API (conflict_block_reason): once one product's
// card is approved the other cannot be, and the approve endpoint refuses it.
export function ConflictNote({
  conflicts,
  blockReason,
}: {
  conflicts: CompanyConflict[] | undefined;
  blockReason?: string | null;
}) {
  if (!conflicts || conflicts.length === 0) return null;
  const blocking = Boolean(blockReason);
  const color = blocking ? "#e05d5d" : "#e8963f";
  return (
    <div
      role="alert"
      className="px-3 py-2 rounded-[10px] mb-2 text-[11.5px]"
      style={{ background: `${color}14`, border: `1px solid ${color}55`, color }}
    >
      <div className="font-bold mb-1">
        {blocking ? "Blocked: this company is already claimed by another product" : "Same company, two products"}
      </div>
      {conflicts.map((c, i) => (
        <div key={`${c.sequence_id ?? c.lead_id}-${i}`} className="flex flex-wrap items-center gap-2">
          <ProductBadge name={c.product} />
          <span style={{ color: "#aab4bd" }}>{describe(c)}</span>
        </div>
      ))}
      <div className="mt-1" style={{ color: "#aab4bd" }}>
        {blocking
          ? blockReason
          : "Only one product can be approved for a company. Approving this one blocks the other."}
      </div>
    </div>
  );
}
