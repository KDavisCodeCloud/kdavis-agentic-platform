// GAPS #34: one line on an Outreach card saying what the contact did after
// opening their ?ref= demo link. Data from /api/demo-activity.
//
// Colors follow the CEO Decoded status mapping: blue = in progress (opened,
// viewed, approved, clicked), green = converted (signed up, paid). Nothing is
// amber or red here -- no demo activity is a problem state, just "not yet".

export type DemoActivityData = {
  demo_opened: number;
  incidents_viewed: number;
  fixes: number;
  signup_clicked: number;
  signed_up: boolean;
  paid_tier: string | null;
  checkout_tier: string | null;
  last_seen: string | null;
};

const BLUE = "#7ea6f5";
const GREEN = "#6fce8f";

function Pill({ text, color }: { text: string; color: string }) {
  return (
    <span className="px-1.5 py-0.5 rounded-[5px] text-[9.5px] font-mono" style={{ background: `${color}22`, color }}>
      {text}
    </span>
  );
}

// known=false while loading or after a failed fetch: render nothing rather
// than claim "not opened yet" about data we don't have.
export function DemoActivity({
  demoRef,
  activity,
  known,
}: {
  demoRef?: string | null;
  activity?: DemoActivityData;
  known: boolean;
}) {
  if (!demoRef || !known) return null;

  if (!activity) {
    return (
      <div className="flex flex-wrap items-center gap-1.5 mt-1 min-w-0 text-[10.5px] font-mono" style={{ color: "#5b6673" }}>
        demo link · not opened yet
      </div>
    );
  }

  const pills: { text: string; color: string }[] = [];
  if (activity.demo_opened) pills.push({ text: `demo opened${activity.demo_opened > 1 ? ` ${activity.demo_opened}×` : ""}`, color: BLUE });
  if (activity.incidents_viewed) pills.push({ text: `${activity.incidents_viewed} incident${activity.incidents_viewed > 1 ? "s" : ""} viewed`, color: BLUE });
  if (activity.fixes) pills.push({ text: `${activity.fixes} fix${activity.fixes > 1 ? "es" : ""} approved`, color: BLUE });
  if (activity.signup_clicked && !activity.signed_up) pills.push({ text: "clicked signup", color: BLUE });
  if (activity.signed_up && !activity.paid_tier) {
    pills.push({ text: activity.checkout_tier ? `signed up · at checkout (${activity.checkout_tier})` : "signed up", color: GREEN });
  }
  if (activity.paid_tier) pills.push({ text: `paid · ${activity.paid_tier}`, color: GREEN });

  return (
    <div className="flex flex-wrap items-center gap-1.5 mt-1 min-w-0">
      <span className="text-[10.5px] font-mono" style={{ color: "#8b96a3" }}>demo</span>
      {pills.map((p) => <Pill key={p.text} text={p.text} color={p.color} />)}
      {activity.last_seen && (
        <span className="text-[10.5px] font-mono" style={{ color: "#5b6673" }}>
          last seen {activity.last_seen.slice(0, 10)}
        </span>
      )}
    </div>
  );
}
