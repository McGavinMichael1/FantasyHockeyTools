import type { Metadata } from 'next';
import { Anton, Barlow, Barlow_Condensed } from 'next/font/google';
import './globals.css';
import './rink.css';

const display = Anton({
  weight: '400',
  subsets: ['latin'],
  variable: '--font-display',
  display: 'swap',
});

const body = Barlow({
  weight: ['400', '500', '600', '700'],
  subsets: ['latin'],
  variable: '--font-body',
  display: 'swap',
});

const condensed = Barlow_Condensed({
  weight: ['500', '600', '700'],
  subsets: ['latin'],
  variable: '--font-cond',
  display: 'swap',
});

export const metadata: Metadata = {
  title: 'The Rink — Fantasy Hockey',
  description: 'Waiver wire targets and cold streaks, read off the ice',
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${display.variable} ${body.variable} ${condensed.variable}`}
    >
      <body className="rink-root">{children}</body>
    </html>
  );
}
