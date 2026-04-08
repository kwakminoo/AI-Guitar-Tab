import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const frontendRoot = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const nextCli = path.join(frontendRoot, "node_modules", "next", "dist", "bin", "next");
const host = process.env.DEV_HOST ?? "127.0.0.1";
const port = process.env.PORT ?? "3000";
const useWebpack = process.argv.includes("--webpack");

const args = ["dev", "-H", host];
if (process.env.PORT) args.push("-p", String(process.env.PORT));
if (useWebpack) args.push("--webpack");

console.log("");
console.log("────────────────────────────────────────");
console.log(`  브라우저에서 열기: http://${host}:${port}`);
console.log("  Ready 이후 터미널에 로그가 없어도 정상입니다.");
console.log("  페이지를 요청하면 GET / … 로그가 이어집니다.");
console.log("  이미 dev 서버가 떠 있다면: Ctrl+C로 끄고 다시 실행하세요.");
console.log("  lock 오류 시: npm run dev:unlock 후 다시 npm run dev");
if (useWebpack) console.log("  (Webpack 모드)");
console.log("────────────────────────────────────────");
console.log("");

const child = spawn(process.execPath, [nextCli, ...args], {
  cwd: frontendRoot,
  stdio: "inherit",
  env: process.env,
});

child.on("exit", (code, signal) => {
  if (signal) process.kill(process.pid, signal);
  process.exit(code ?? 1);
});
