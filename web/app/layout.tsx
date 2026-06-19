/**
 * web/app/layout.tsx
 * RxWatcher root layout — dark navy header with logo, wraps all pages.
 * Applies global CSS variables and Inter font.
 *
 * Copyright (c) 2026 Wayne Ohm / YC Lab. All rights reserved.
 */

import type { Metadata } from 'next'
import { Inter } from 'next/font/google'
import './globals.css'
import Link from 'next/link'

const inter = Inter({ subsets: ['latin'] })

export const metadata: Metadata = {
  title: 'RxWatcher — YC Lab',
  description: 'iTero scan analysis dashboard',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className={inter.className}>
        <header className="header">
          <div className="header-inner">
            <Link href="/" className="logo">
              <span className="logo-icon">🦷</span>
              <span className="logo-text">Rx<span className="logo-accent">Watcher</span></span>
            </Link>
            <span className="logo-sub">YC Lab · Scan Review</span>
            <Link href="/clinics" style={{
              marginLeft: 'auto', fontSize: 12, color: 'var(--muted)',
              textDecoration: 'none', padding: '4px 10px',
              border: '1px solid var(--border)', borderRadius: 5,
            }}>
              🏥 Clinics
            </Link>
          </div>
        </header>
        <main className="main-content">
          {children}
        </main>
      </body>
    </html>
  )
}