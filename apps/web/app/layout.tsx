/**
 * Root layout.
 *
 * Typography is bound here and consumed everywhere through the TAM role names
 * (--tam-font-body-sans / --tam-font-body-mono, rebound in globals.css).
 *
 * The IBM Plex faces are loaded with next/font/local from the OFL files that
 * @theam/brand-system already ships. That avoids a build-time network fetch
 * (next/font/google), needs nothing copied into public/, and keeps the fonts
 * versioned with the brand package.
 *
 * NOTE: proto forbids Neue Galano and Montserrat, which is exactly what
 * tokens.css resolves --tam-font-display to. The display register is IBM Plex
 * Sans Medium instead, exposed as --limina-font-display in globals.css.
 * Nothing in this app may reference --tam-font-display.
 */

import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";

import localFont from "next/font/local";

import "./globals.css";

const plexSans = localFont({
  src: [
    {
      path: "../node_modules/@theam/brand-system/dist/assets/typography/ibm-plex/sans/IBMPlexSans-Regular.woff2",
      weight: "400",
      style: "normal",
    },
    {
      path: "../node_modules/@theam/brand-system/dist/assets/typography/ibm-plex/sans/IBMPlexSans-Italic.woff2",
      weight: "400",
      style: "italic",
    },
    {
      path: "../node_modules/@theam/brand-system/dist/assets/typography/ibm-plex/sans/IBMPlexSans-Medium.woff2",
      weight: "500",
      style: "normal",
    },
    {
      path: "../node_modules/@theam/brand-system/dist/assets/typography/ibm-plex/sans/IBMPlexSans-MediumItalic.woff2",
      weight: "500",
      style: "italic",
    },
  ],
  variable: "--limina-font-sans",
  display: "swap",
  fallback: ["system-ui", "sans-serif"],
});

const plexMono = localFont({
  src: [
    {
      path: "../node_modules/@theam/brand-system/dist/assets/typography/ibm-plex/mono/IBMPlexMono-Regular.woff2",
      weight: "400",
      style: "normal",
    },
    {
      path: "../node_modules/@theam/brand-system/dist/assets/typography/ibm-plex/mono/IBMPlexMono-Italic.woff2",
      weight: "400",
      style: "italic",
    },
    {
      path: "../node_modules/@theam/brand-system/dist/assets/typography/ibm-plex/mono/IBMPlexMono-Medium.woff2",
      weight: "500",
      style: "normal",
    },
    {
      path: "../node_modules/@theam/brand-system/dist/assets/typography/ibm-plex/mono/IBMPlexMono-MediumItalic.woff2",
      weight: "500",
      style: "italic",
    },
  ],
  variable: "--limina-font-mono",
  display: "swap",
  fallback: ["ui-monospace", "monospace"],
});

export const metadata: Metadata = {
  title: {
    default: "Limina Console",
    template: "%s · Limina Console",
  },
  description:
    "Attention-first operations and evidence workspace for autonomous research projects.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={`${plexSans.variable} ${plexMono.variable}`}>
      {/*
        Theme follows the system preference via prefers-color-scheme in
        globals.css. Adding "light" or "dark" to <html> overrides it.
      */}
      <body>
        {/* Auth/query providers wrap here when the page layer needs them. */}
        {children}
      </body>
    </html>
  );
}
