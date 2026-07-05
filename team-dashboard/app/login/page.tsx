"use client";
import { useState } from "react";
import { createClient } from "@/lib/supabase/client";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [loading, setLoading] = useState(false);

  async function handleLogin(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    const supabase = createClient();
    await supabase.auth.signInWithOtp({
      email,
      options: { emailRedirectTo: `${location.origin}/auth/callback` },
    });
    setSent(true);
    setLoading(false);
  }

  return (
    <div
      className="min-h-screen flex items-center justify-center"
      style={{ backgroundColor: "#0d1117" }}
    >
      <div
        className="w-full max-w-sm rounded-[14px] p-8"
        style={{ backgroundColor: "#141c28", border: "1px solid #1c2535" }}
      >
        {/* Brand mark */}
        <div className="flex items-center gap-3 mb-8">
          <div
            className="w-8 h-8 rounded-[8px] flex items-center justify-center text-[13px] font-bold shrink-0"
            style={{ backgroundColor: "#5eead4", color: "#0d1117" }}
          >
            T
          </div>
          <div>
            <p className="text-[14px] font-bold leading-none" style={{ color: "#eef2f5" }}>
              THD STACK
            </p>
            <p className="text-[10px] font-mono mt-0.5" style={{ color: "#5b6673" }}>
              Team Dashboard
            </p>
          </div>
        </div>

        {!sent ? (
          <form onSubmit={handleLogin}>
            <p className="text-[13px] font-semibold mb-1" style={{ color: "#eef2f5" }}>
              Sign in
            </p>
            <p className="text-[12px] mb-5" style={{ color: "#aab4bd" }}>
              Enter your email to receive a magic link.
            </p>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="your@email.com"
              required
              className="w-full rounded-[10px] px-3 py-2.5 text-[13px] outline-none mb-4"
              style={{
                backgroundColor: "#111825",
                border: "1px solid #1c2535",
                color: "#eef2f5",
              }}
            />
            <button
              type="submit"
              disabled={loading || !email}
              className="w-full h-10 rounded-[10px] text-[13px] font-semibold transition-opacity disabled:opacity-40"
              style={{ backgroundColor: "#5eead4", color: "#0d1117" }}
            >
              {loading ? "Sending…" : "Send magic link"}
            </button>
          </form>
        ) : (
          <div className="text-center">
            <p className="text-[13px] font-semibold mb-2" style={{ color: "#eef2f5" }}>
              Check your email
            </p>
            <p className="text-[12px]" style={{ color: "#aab4bd" }}>
              Magic link sent to <span style={{ color: "#5eead4" }}>{email}</span>.
              Click the link to access your dashboard.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
