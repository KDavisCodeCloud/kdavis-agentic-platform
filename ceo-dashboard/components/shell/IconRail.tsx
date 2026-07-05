import type { Role } from "@/lib/types";

const TEAM = [
  { initials: "K", title: "Kelvin — CEO", bg: "#5eead422", text: "#5eead4" },
  { initials: "W", title: "Wife — COO",   bg: "#6fce8f22", text: "#6fce8f" },
  { initials: "S", title: "Son — CTO",    bg: "#7ea6f522", text: "#7ea6f5" },
];

export function IconRail({ role }: { role: Role }) {
  return (
    <aside
      className="flex flex-col items-center py-4 gap-4 shrink-0"
      style={{
        width: "60px",
        backgroundColor: "#0e1218",
        borderRight: "1px solid #1c222b",
        height: "100vh",
      }}
    >
      {/* Brand mark */}
      <div
        className="w-8 h-8 rounded-[8px] flex items-center justify-center text-[13px] font-bold"
        style={{ backgroundColor: "#5eead4", color: "#0b0e13" }}
        title="CEO Decoded"
      >
        C
      </div>

      <div className="w-full h-px" style={{ backgroundColor: "#1c222b" }} />

      {/* Team member avatars */}
      {TEAM.map((member) => (
        <div
          key={member.initials}
          className="w-[34px] h-[34px] rounded-[10px] flex items-center justify-center text-[11px] font-bold"
          style={{ backgroundColor: member.bg, color: member.text }}
          title={member.title}
        >
          {member.initials}
        </div>
      ))}
    </aside>
  );
}
