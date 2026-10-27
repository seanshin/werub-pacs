import type { Config } from 'tailwindcss';

const config: Config = {
  darkMode: 'class',
  content: ['./src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        primary: { DEFAULT: '#2563eb', dark: '#1d4ed8' },
        danger: '#dc2626',
        warning: '#f59e0b',
        success: '#16a34a',
      },
    },
  },
  plugins: [],
};

export default config;
