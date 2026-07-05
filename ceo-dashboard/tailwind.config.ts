import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./lib/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        base: "#0b0e13",
        sidebar: "#0e1218",
        card: "#141a22",
        tile: "#10151b",
        border: "#1c222b",
        "text-primary": "#eef2f5",
        "text-section": "#c7cfd6",
        "text-body": "#aab4bd",
        "text-muted": "#5b6673",
        "text-label": "#8b96a3",
        mint: "#5eead4",
        "mint-dim": "#5eead41a",
        green: "#6fce8f",
        "green-dim": "#6fce8f22",
        amber: "#e8963f",
        "amber-dim": "#e8963f22",
        "amber-solid": "#332a18",
        red: "#e05d5d",
        "red-dim": "#e05d5d22",
        blue: "#7ea6f5",
        "blue-dim": "#5b8def22",
        "gray-badge": "#9aa2ab",
        "gray-badge-bg": "#2a2a2a",
        "exit-gate-border": "#1f3d2e",
        "legal-bg": "#241a10",
        "legal-border": "#3d2e1f",
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "Fira Code", "monospace"],
      },
      fontSize: {
        "metric": ["24px", { fontWeight: "800", lineHeight: "1.1" }],
        "page-title": ["19px", { fontWeight: "700", lineHeight: "1.2" }],
        "card-title": ["14px", { fontWeight: "700", lineHeight: "1.3" }],
        "section-label": ["13px", { fontWeight: "700", lineHeight: "1.3" }],
        "body": ["12.5px", { fontWeight: "400", lineHeight: "1.5" }],
        "badge": ["10px", { fontWeight: "600", lineHeight: "1" }],
        "mono-sm": ["11px", { fontWeight: "400", lineHeight: "1.4" }],
      },
      borderRadius: {
        card: "14px",
        tile: "10px",
        badge: "5px",
        "badge-pill": "20px",
        avatar: "50%",
        "avatar-sq": "10px",
      },
      spacing: {
        "rail": "60px",
        "sidebar": "196px",
      },
    },
  },
  plugins: [],
};

export default config;
