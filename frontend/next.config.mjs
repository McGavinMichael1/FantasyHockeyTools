// Set only by scripts/deploy_draft_board.ps1: a static, draft-board-only build
// for the league-hosted site. Dev and plain `npm run build` are unaffected.
const draftOnly = process.env.NEXT_PUBLIC_FHT_DRAFT_ONLY === '1';

/** @type {import('next').NextConfig} */
const nextConfig = {
  images: {
    remotePatterns: [
      {
        protocol: 'https',
        hostname: 'assets.nhle.com',
        pathname: '/mugs/nhl/**',
      },
    ],
  },
  ...(draftOnly && {
    output: 'export',
    // Every page/layout is .tsx and both API route handlers are .ts, so this
    // drops /api/players and /api/keeper-chat -- a static export cannot serve
    // them, and keeper chat must not ship with the owner's API key anyway.
    // The page reads /frontend_data.json instead.
    pageExtensions: ['tsx'],
  }),
};

export default nextConfig;
