import { StatusBadge } from "@/components/ui/StatusBadge";

type Props = {
  taskName: string;
  status?: string;
};

export function TopBar({ taskName, status }: Props) {
  return (
    <header
      className="shrink-0 flex items-center justify-between px-8"
      style={{
        height: "52px",
        borderBottom: "1px solid #1c2535",
        backgroundColor: "#0d1117",
      }}
    >
      <p className="text-[19px] font-bold truncate-text min-w-0" style={{ color: "#eef2f5" }}>
        {taskName}
      </p>
      <div className="flex items-center gap-3 shrink-0">
        {status && <StatusBadge status={status} />}
        <div
          className="w-[30px] h-[30px] rounded-full flex items-center justify-center text-[12px] font-bold"
          style={{ backgroundColor: "#5eead4", color: "#0d1117" }}
        >
          B
        </div>
      </div>
    </header>
  );
}
