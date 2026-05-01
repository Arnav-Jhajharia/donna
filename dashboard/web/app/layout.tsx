import type { Metadata } from 'next';
import { EB_Garamond, Red_Hat_Text, JetBrains_Mono, Caveat } from 'next/font/google';
import './globals.css';

// Landing-page fonts. The dashboard's existing CSS references
// `--font-serif` and `--font-sans` (EB Garamond + Red Hat Text), so the
// dashboard surface picks up the same Google-hosted fonts when these
// CSS variables are set on <html>. JetBrains Mono and Caveat are used
// only by the landing page (mono samples + the Donna-promise signature).
const garamond = EB_Garamond({
  subsets: ['latin'],
  weight: ['400', '500'],
  style: ['normal', 'italic'],
  display: 'swap',
  variable: '--font-serif',
});

const redHat = Red_Hat_Text({
  subsets: ['latin'],
  weight: ['400', '500', '600', '700'],
  display: 'swap',
  variable: '--font-sans',
});

const jetbrains = JetBrains_Mono({
  subsets: ['latin'],
  weight: ['400', '500'],
  display: 'swap',
  variable: '--font-mono',
});

const caveat = Caveat({
  subsets: ['latin'],
  weight: ['600'],
  display: 'swap',
  variable: '--font-signature',
});

export const metadata: Metadata = {
  title: 'Donna',
  description: 'A presence with memory. On WhatsApp.',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      className={`${garamond.variable} ${redHat.variable} ${jetbrains.variable} ${caveat.variable}`}
    >
      <body>{children}</body>
    </html>
  );
}
