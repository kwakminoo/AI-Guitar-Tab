/**
 * vendor/alphaTab 빌드 산출물을 Next 정적 경로 public/alphatab-assets 로 복사한다.
 * (alphaTab.mjs + worker + soundfont — ESM 재생에 필요)
 */
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const frontendRoot = path.resolve(__dirname, "..");
const repoRoot = path.resolve(frontendRoot, "..");
const dist = path.join(repoRoot, "vendor", "alphaTab", "packages", "alphatab", "dist");
const dest = path.join(frontendRoot, "public", "alphatab-assets");

function copyFile(src, dst) {
  fs.mkdirSync(path.dirname(dst), { recursive: true });
  fs.copyFileSync(src, dst);
}

function copyDir(srcDir, destDir) {
  if (!fs.existsSync(srcDir)) return;
  fs.mkdirSync(destDir, { recursive: true });
  for (const ent of fs.readdirSync(srcDir, { withFileTypes: true })) {
    const s = path.join(srcDir, ent.name);
    const d = path.join(destDir, ent.name);
    if (ent.isDirectory()) copyDir(s, d);
    else fs.copyFileSync(s, d);
  }
}

if (!fs.existsSync(dist)) {
  console.error("missing vendor dist:", dist);
  process.exit(1);
}

const files = [
  "alphaTab.mjs",
  "alphaTab.min.mjs",
  "alphaTab.core.mjs",
  "alphaTab.core.min.mjs",
  "alphaTab.worker.mjs",
  "alphaTab.worker.min.mjs",
  "alphaTab.worklet.mjs",
  "alphaTab.worklet.min.mjs",
  "alphaTab.js",
  "alphaTab.min.js",
];
for (const f of files) {
  const s = path.join(dist, f);
  if (fs.existsSync(s)) copyFile(s, path.join(dest, f));
}

copyDir(path.join(dist, "font"), path.join(dest, "font"));
copyDir(path.join(dist, "soundfont"), path.join(dest, "soundfont"));

console.log("alphatab-assets ->", dest);
