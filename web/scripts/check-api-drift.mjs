import { mkdtemp, readFile, rm } from "node:fs/promises";
import { spawnSync } from "node:child_process";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

const privateFields = [
  "request_fingerprint",
  "snapshot_fingerprint",
  "reusable_fingerprint",
  "parameters_fingerprint",
];

function run(command, args) {
  const result = spawnSync(command, args, {
    cwd: process.cwd(),
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
  });
  if (result.status !== 0) {
    throw new Error(
      `Command failed: ${command} ${args.join(" ")}\n${result.stderr || result.stdout}`,
    );
  }
}

const temporaryDirectory = await mkdtemp(join(tmpdir(), "macrovision-openapi-"));
try {
  const snapshot = join(temporaryDirectory, "macrovision.openapi.json");
  const schema = join(temporaryDirectory, "schema.ts");
  const python =
    process.env.PYTHON ??
    (process.platform === "win32"
      ? resolve("..", ".venv", "Scripts", "python.exe")
      : "python");

  run(python, [
    resolve("..", "scripts", "export_openapi.py"),
    "--output",
    snapshot,
  ]);
  run(process.execPath, [
    resolve("node_modules", "openapi-typescript", "bin", "cli.js"),
    snapshot,
    "-o",
    schema,
  ]);

  const [expectedSnapshot, generatedSnapshot, expectedSchema, generatedSchema] =
    await Promise.all([
      readFile(resolve("openapi", "macrovision.openapi.json"), "utf8"),
      readFile(snapshot, "utf8"),
      readFile(resolve("src", "lib", "api", "generated", "schema.ts"), "utf8"),
      readFile(schema, "utf8"),
    ]);

  if (expectedSnapshot !== generatedSnapshot) {
    throw new Error("OpenAPI snapshot drift detected; regenerate the snapshot.");
  }
  if (expectedSchema !== generatedSchema) {
    throw new Error("Generated TypeScript API schema drift detected.");
  }
  const leaked = privateFields.filter((field) => expectedSnapshot.includes(field));
  if (leaked.length > 0) {
    throw new Error(`Private Analytics fields leaked into OpenAPI: ${leaked.join(", ")}`);
  }
  console.log("OpenAPI snapshot and generated TypeScript schema are reproducible.");
} finally {
  await rm(temporaryDirectory, { recursive: true, force: true });
}
