import { IconRail } from "./IconRail";
import { Sidebar } from "./Sidebar";

export function TeamShell({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="flex h-screen overflow-hidden"
      style={{ backgroundColor: "#0d1117" }}
    >
      {/* Desktop only: icon rail + sidebar */}
      <div className="hidden md:flex">
        <IconRail />
        <Sidebar />
      </div>

      {/* Main content */}
      <main className="flex-1 flex flex-col h-screen overflow-hidden min-w-0">
        {children}
      </main>
    </div>
  );
}
