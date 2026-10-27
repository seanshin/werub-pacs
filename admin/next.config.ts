import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  basePath: '/pacs-admin',
  output: 'standalone',
  async rewrites() {
    return [
      { source: '/api/:path*', destination: 'http://localhost:8000/api/:path*' },
    ];
  },
};

export default nextConfig;
