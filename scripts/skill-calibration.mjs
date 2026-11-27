import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const args = process.argv.slice(2);
let database = process.env.APPDATA ? path.join(process.env.APPDATA, "dev.fumen.app", "library.db") : null;
let output = path.join(root, "tools", "skill-calibration", ".cache");
let reportOnly = false;
for (let i = 0; i < args.length; i++) {
  if (args[i] === "--report-only") reportOnly = true;
  else if (args[i] === "--db" && args[i + 1]) database = path.resolve(args[++i]);
  else if (args[i] === "--out" && args[i + 1]) output = path.resolve(args[++i]);
  else throw new Error("Usage: npm run calibrate:preview -- [--db PATH] [--out PATH] [--report-only]");
}
function run(command, argv) {
  const result = spawnSync(command, argv, { cwd: root, stdio: "inherit" });
  if (result.error) throw result.error;
  if (result.status !== 0) process.exit(result.status ?? 1);
}
if (!reportOnly) {
  if (!database) throw new Error("Pass --db with your imported Fumen library.db path.");
  run("cargo", ["run", "--manifest-path", "src-tauri/Cargo.toml", "--example", "calibration_preview", "--", database, output]);
}
run(process.env.PYTHON ?? (process.platform === "win32" ? "python" : "python3"), ["tools/skill-calibration/curve_preview.py", "--out", output]);
