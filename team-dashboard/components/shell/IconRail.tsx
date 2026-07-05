export function IconRail() {
  return (
    <aside
      className="shrink-0 flex flex-col items-center pt-4 pb-4 gap-3 h-screen"
      style={{
        width: "60px",
        backgroundColor: "#0f1520",
        borderRight: "1px solid #1c2535",
      }}
    >
      {/* Brand mark */}
      <div
        className="w-8 h-8 rounded-[8px] flex items-center justify-center text-[13px] font-bold"
        style={{ backgroundColor: "#5eead4", color: "#0d1117" }}
      >
        T
      </div>

      <div className="flex-1" />

      {/* Builder avatar */}
      <div
        className="w-[34px] h-[34px] rounded-[8px] flex items-center justify-center text-[11px] font-bold"
        style={{ backgroundColor: "#5eead422", color: "#5eead4" }}
        title="Builder"
      >
        B
      </div>
    </aside>
  );
}
