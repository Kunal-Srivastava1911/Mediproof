/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        band: {
          green: "#15803d",
          amber: "#b45309",
          red: "#b91c1c",
        },
      },
    },
  },
  plugins: [],
};
