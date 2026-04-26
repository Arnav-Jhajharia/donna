/** @type {import('tailwindcss').Config} */
// DONNA · Tailwind config
// Do not extend colors/fonts/sizes with arbitrary values.
// If a screen needs something not here, the screen is wrong — not the config.

module.exports = {
  content: [
    './src/**/*.{js,jsx,ts,tsx,html,mdx}',
    './app/**/*.{js,jsx,ts,tsx,html,mdx}',
    './pages/**/*.{js,jsx,ts,tsx,html,mdx}',
    './components/**/*.{js,jsx,ts,tsx}',
  ],
  theme: {
    // Replace, don't extend — the palette is closed.
    colors: {
      transparent: 'transparent',
      current: 'currentColor',

      paper:   { DEFAULT: '#FBF7F5', 50: '#FDFAF8', 100: '#FBF7F5', 200: '#F5EFEA', 300: '#F0EAE4', 400: '#E7DFD7', 500: '#D6CAC0' },
      surface: { DEFAULT: '#F0EAE4', pressed: '#E7DFD7' },
      ink:     { DEFAULT: '#1E1A18', 200: '#D9CEC5', 300: '#B5A89F', 400: '#8F837C', 500: '#6B615C', 700: '#3A3331', 900: '#1E1A18' },
      rust:    { DEFAULT: '#7B5544', 50: '#F5EFEA', 100: '#EBDCD2', 300: '#C9A796', 500: '#A07562', 700: '#7B5544', 900: '#4A2F23' },
      muted:   '#6B615C',

      // Signals — semantic use only.
      moss:    { DEFAULT: '#5C6B4A', tint: '#EEF1E7' },
      amber:   { DEFAULT: '#A8804A', tint: '#F5EBD9' },
      oxblood: { DEFAULT: '#8B3A2E', tint: '#F3E0DC' },
    },
    fontFamily: {
      serif: ['EB Garamond', 'Garamond', 'Georgia', 'serif'],
      sans:  ['Red Hat Text', '-apple-system', 'BlinkMacSystemFont', 'Inter', 'sans-serif'],
      mono:  ['JetBrains Mono', 'SF Mono', 'Menlo', 'monospace'],
    },
    fontSize: {
      // Role-named, not t-shirt sized.
      display: ['64px', { lineHeight: '65px', letterSpacing: '-0.025em', fontWeight: '400' }],
      h1:      ['44px', { lineHeight: '48px', letterSpacing: '-0.02em',  fontWeight: '400' }],
      h2:      ['32px', { lineHeight: '36px', letterSpacing: '-0.015em', fontWeight: '400' }],
      h3:      ['22px', { lineHeight: '28px', letterSpacing: '-0.01em',  fontWeight: '500' }],
      h4:      ['15px', { lineHeight: '20px', fontWeight: '600' }],
      lead:    ['18px', { lineHeight: '29px', fontWeight: '400' }],
      body:    ['16px', { lineHeight: '25px', fontWeight: '400' }],
      small:   ['14px', { lineHeight: '22px', fontWeight: '400' }],
      caption: ['12px', { lineHeight: '18px', fontWeight: '400' }],
      label:   ['11px', { lineHeight: '16px', letterSpacing: '0.14em', fontWeight: '500' }],
      button:  ['15px', { lineHeight: '1',   fontWeight: '500' }],
      input:   ['16px', { lineHeight: '25px', fontWeight: '400' }],
    },
    fontWeight: {
      regular:  '400',
      medium:   '500',
      semibold: '600',
      bold:     '700', // tabular numerals only — linted
    },
    spacing: {
      0: '0', 1: '4px', 2: '8px', 3: '12px', 4: '16px',
      5: '24px', 6: '32px', 7: '48px', 8: '64px', 9: '96px', 10: '128px',
    },
    borderRadius: {
      none: '0', sm: '4px', md: '8px', lg: '12px', full: '9999px',
    },
    borderWidth: {
      0: '0', hairline: '1px', focus: '2px',
    },
    boxShadow: {
      // No default. Cards elevate via hairline or surface swap.
      none: 'none',
      modal:   '0 16px 48px -12px rgba(30,26,24,0.18), 0 4px 12px -4px rgba(30,26,24,0.08)',
      toast:   '0 8px 24px -8px rgba(30,26,24,0.16)',
      popover: '0 4px 16px -4px rgba(30,26,24,0.12)',
    },
    transitionTimingFunction: {
      standard: 'cubic-bezier(0.2, 0, 0, 1)',
      emphasis: 'cubic-bezier(0.3, 0, 0, 1)',
    },
    transitionDuration: {
      instant: '80ms', fast: '160ms', base: '240ms', slow: '400ms',
    },
    extend: {
      // Only additive utilities here. Never color/type/space.
    },
  },
  plugins: [],
  // Disable arbitrary values at the config level in your linter.
  // See .stylelintrc and eslint-plugin-donna rules.
};
