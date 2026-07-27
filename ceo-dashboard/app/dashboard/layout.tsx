import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { IconRail } from "@/components/shell/IconRail";
import { Sidebar } from "@/components/shell/Sidebar";
import { MobileNav } from "@/components/shell/MobileNav";
import { OWNER_EMAIL, resolveRole } from "@/lib/role";

export default async function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const supabase = await createClient();
  const { data: { user } } = await supabase.auth.getUser();

  if (!user) redirect("/login");

  const role = resolveRole(user.email, user.user_metadata?.role);
  const initials = user.email === OWNER_EMAIL
    ? "KD"
    : user.user_metadata?.name
      ? user.user_metadata.name.split(" ").map((n: string) => n[0]).join("").slice(0, 2).toUpperCase()
      : user.email?.[0]?.toUpperCase() ?? "?";

  return (
    <div className="flex flex-col md:flex-row h-screen overflow-hidden bg-base">
      {/* Desktop shell — icon rail (60px) + labeled sidebar (196px). Hidden
          below md; MobileNav below replaces both with a hamburger + drawer. */}
      <div className="hidden md:flex">
        <IconRail role={role} />
        <Sidebar role={role} />
      </div>

      {/* Mobile shell — hamburger top bar + slide-out drawer, hidden at md+ */}
      <MobileNav role={role} />

      {/* Main content — flex */}
      <main className="flex-1 flex flex-col overflow-hidden min-w-0">
        {children}
      </main>
    </div>
  );
}
