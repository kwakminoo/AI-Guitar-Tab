import path from "node:path";
import type { NextConfig } from "next";

// `next build`는 보통 frontend 디렉터리에서 실행됨
// Turbopack(Windows): 백슬래시 절대경로는 "windows imports are not implemented yet" → 슬래시로 통일
const alphatabPackageRoot = path
  .resolve(process.cwd(), "../vendor/alphaTab/packages/alphatab")
  .replace(/\\/g, "/");

const backendOrigin =
  process.env.BACKEND_URL ?? process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  reactCompiler: true,
  transpilePackages: ["@coderline/alphatab"],
  // 브라우저는 Next(3000)와 동일 출처로 /api/* 호출 → CORS 프리플라이트 없이 FastAPI로 전달
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${backendOrigin}/api/:path*`,
      },
    ];
  },
  // Turbopack은 repo 밖 file: 링크 패키지를 기본으로 못 찾는 경우가 있어 절대 경로로 고정
  turbopack: {
    resolveAlias: {
      "@coderline/alphatab": alphatabPackageRoot,
    },
  },
};

export default nextConfig;
