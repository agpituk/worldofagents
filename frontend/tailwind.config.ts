import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#0e0d0a",
        "bg-card": "#19170f",
        border: "#2d2820",
        fg: "#e8e0cf",
        "fg-muted": "#968a72",
        amber: {
          DEFAULT: "#f0a800",
          dim: "#a07a18",
        },
        blood: "#b04030",
      },
      fontFamily: {
        display: ["ui-serif", "Georgia", "serif"],
        mono: ["ui-monospace", "JetBrains Mono", "Menlo", "monospace"],
      },
    },
  },
  plugins: [],
};

export default config;
