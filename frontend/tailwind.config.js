/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        paper: "#F7F3EA",
        ink: "#1C1B19",
        turmeric: "#E08E1D",
        basil: "#3E6B4F",
        chili: "#C4432B",
        rule: "#D8D2C4",
      },
      fontFamily: {
        display: ["'Archivo Black'", "sans-serif"],
        label: ["'Barlow Condensed'", "sans-serif"],
        mono: ["'IBM Plex Mono'", "monospace"],
      },
    },
  },
  plugins: [],
};
