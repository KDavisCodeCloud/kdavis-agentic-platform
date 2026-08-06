import Link from "next/link";

// Was duplicated verbatim in current-task/page.tsx and tasks/page.tsx, and
// had drifted between the two copies: current-task's version was
// `fixed bottom-0 left-0 right-0 z-50`, tasks' was not, so the same "shared"
// nav behaved differently depending which page you were on. resources/page.tsx
// reserved bottom padding (`pb-20 md:pb-6`) for this bar but never rendered
// it at all -- a real dead end on mobile, with no way back to Tasks or
// Current Task short of the browser back button. Extracted once, fixed
// positioning applied consistently, and wired into all three pages.
export function MobileTabBar({ active }: { active: "tasks" | "current" | "build-queue" | "resources" }) {
  const tabs = [
    { label: "My Tasks",     href: "/tasks",        key: "tasks" },
    { label: "Current Task", href: "/current-task", key: "current" },
    { label: "Build Queue",  href: "/build-queue",  key: "build-queue" },
    { label: "Resources",    href: "/resources",    key: "resources" },
  ] as const;

  return (
    <nav
      className="flex md:hidden shrink-0 fixed bottom-0 left-0 right-0 z-50"
      style={{
        height: "48px",
        backgroundColor: "#0f1520",
        borderTop: "1px solid #1c2535",
      }}
    >
      {tabs.map((tab) => (
        <Link
          key={tab.key}
          href={tab.href}
          className="flex-1 flex items-center justify-center text-[11px] font-semibold transition-colors"
          style={{
            color: active === tab.key ? "#5eead4" : "#5b6673",
            borderTop: active === tab.key ? "2px solid #5eead4" : "2px solid transparent",
          }}
        >
          {tab.label}
        </Link>
      ))}
    </nav>
  );
}
