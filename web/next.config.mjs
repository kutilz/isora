/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Docs content lives in web/content; nothing outside web/ is needed at build.
  async headers() {
    return [
      {
        // A stale service worker keeps serving a stale app forever, so this one
        // file must always be revalidated, and it needs root scope.
        source: "/sw.js",
        headers: [
          { key: "Cache-Control", value: "public, max-age=0, must-revalidate" },
          { key: "Service-Worker-Allowed", value: "/" },
        ],
      },
    ];
  },
};

export default nextConfig;
