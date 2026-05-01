// Postcss config for Tailwind v4. The landing-page surface relies on
// Tailwind utilities; the dashboard uses raw CSS. Tailwind's content
// scope (set in tailwind.config.js) is restricted to the landing
// directories so the dashboard's stylesheet keeps its precedence.
export default {
  plugins: {
    '@tailwindcss/postcss': {},
  },
};
