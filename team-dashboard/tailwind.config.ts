import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        base:    "#0d1117",
        sidebar: "#0f1520",
        card:    "#141c28",
        tile:    "#111825",
        border:  "#1c2535",
        mint:    "#5eead4",
        green:   "#6fce8f",
        amber:   "#e8963f",
        red:     "#e05d5d",
        blue:    "#7ea6f5",
      },
      fontFamily: {
        sans: ["Inter", "sans-serif"],
        mono: ["JetBrains Mono", "monospace"],
      },
    },
  },
  plugins: [],
};

export default config;
