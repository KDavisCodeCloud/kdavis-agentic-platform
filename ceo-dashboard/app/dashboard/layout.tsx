import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { IconRail } from "@/components/shell/IconRail";
import { Sidebar } from "@/components/shell/Sidebar";
import type { Role } from "@/lib/types";

export default async function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const supabase = await createClient();
  const { data: { user } } = await supabase.auth.getUser();

  if (!user) redirect("/login");

  const OWNER_EMAIL = "kdav2k5@gmail.com";
  const role = (user.email === OWNER_EMAIL ? "admin" : (user.user_metadata?.role ?? "rnd")) as Role;
  const initials = user.email === OWNER_EMAIL
    ? "KD"
    : user.user_metadata?.name
      ? user.user_metadata.name.split(" ").map((n: string) => n[0]).join("").slice(0, 2).toUpperCase()
      : user.email?.[0]?.toUpperCase() ?? "?";

  return (
    <div className="flex h-screen overflow-hidden bg-base">
      {/* Icon rail — 60px */}
      <IconRail role={role} />

      {/* Labeled sidebar — 196px */}
      <Sidebar role={role} />

      {/* Main content — flex */}
      <main className="flex-1 flex flex-col h-screen overflow-hidden min-w-0">
        {children}
      </main>
    </div>
  );
}
