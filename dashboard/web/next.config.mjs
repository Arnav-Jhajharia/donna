/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Allow a second `next dev` instance to coexist with the first by
  // pointing it at a separate build dir. Set NEXT_DIST_DIR=.next-internal
  // for the internal-surface dev server (port 3001) so Next 16's
  // project-singleton lock doesn't reject it.
  distDir: process.env.NEXT_DIST_DIR || '.next',
};

export default nextConfig;
