import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const frontendRoot = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const lockPath = path.join(frontendRoot, ".next", "dev", "lock");

try {
  fs.rmSync(lockPath, { force: true });
  console.log(`삭제함: ${lockPath}`);
} catch {
  console.log("(락 파일이 없거나 삭제할 수 없습니다.)");
}
