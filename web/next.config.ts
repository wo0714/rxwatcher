/**
 * web/next.config.ts
 * Next.js configuration for RxWatcher.
 * Transpiles Three.js packages to fix Turbopack/SWC compatibility.
 *
 * Copyright (c) 2026 Wayne Ohm / YC Lab. All rights reserved.
 */

import type { NextConfig } from 'next'

const nextConfig: NextConfig = {
  transpilePackages: ['three', '@react-three/fiber', '@react-three/drei'],
  allowedDevOrigins: ['localhost', '127.0.0.1', '192.168.1.190', '192.168.50.155'],
}

export default nextConfig