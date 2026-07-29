import { createServer } from "node:http";
import { spawn } from "node:child_process";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

const upstreamPort = Number(process.env.SMOKE_UPSTREAM_PORT ?? "8100");
const webPort = Number(process.env.SMOKE_WEB_PORT ?? "3100");
const host = "127.0.0.1";
const decimal = "1234567890.12345678";
const webBase = `http://${host}:${webPort}`;
let queryObserved = false;

const upstream = createServer((request, response) => {
  if (request.url === "/api/v1/smoke?probe=preserved") {
    queryObserved = true;
    response.writeHead(200, { "content-type": "application/json" });
    response.end(JSON.stringify({ value: decimal, query: "preserved" }));
    return;
  }
  if (request.url === "/api/v1/smoke/failure") {
    response.writeHead(409, { "content-type": "application/json" });
    response.end(JSON.stringify({ error: { code: "intentional_conflict" } }));
    return;
  }
  response.writeHead(404, { "content-type": "application/json" });
  response.end(JSON.stringify({ error: { code: "not_found" } }));
});

async function listen(server, port) {
  await new Promise((resolvePromise, reject) => {
    server.once("error", reject);
    server.listen(port, host, resolvePromise);
  });
}

async function close(server) {
  await new Promise((resolvePromise) => server.close(resolvePromise));
}

async function waitForApplication() {
  for (let attempt = 0; attempt < 80; attempt += 1) {
    try {
      const response = await fetch(`${webBase}/fa`);
      if (response.ok) return;
    } catch {
      // The application is still starting.
    }
    await new Promise((resolvePromise) => setTimeout(resolvePromise, 250));
  }
  throw new Error("Built Next.js application did not become ready.");
}

await listen(upstream, upstreamPort);
const nextProcess = spawn(
  process.execPath,
  [resolve("node_modules", "next", "dist", "bin", "next"), "start", "-H", host, "-p", String(webPort)],
  {
    cwd: process.cwd(),
    env: {
      ...process.env,
      MACROVISION_BACKEND_URL: `http://${host}:${upstreamPort}`,
    },
    stdio: ["ignore", "pipe", "pipe"],
  },
);

nextProcess.stdout.resume();
nextProcess.stderr.resume();

try {
  await waitForApplication();

  const root = await fetch(`${webBase}/`, { redirect: "manual" });
  if (![307, 308].includes(root.status) || root.headers.get("location") !== "/fa") {
    throw new Error(`Unexpected root redirect: ${root.status} ${root.headers.get("location")}`);
  }

  const staticRoutes = [
    "/fa",
    "/fa/markets",
    "/fa/macro",
    "/fa/indicators",
    "/fa/indicators/DEMO.SERIES",
    "/fa/compare",
    "/fa/research",
    "/fa/methodology",
    "/fa/about",
  ];
  for (const route of staticRoutes) {
    const response = await fetch(`${webBase}${route}`);
    if (!response.ok) throw new Error(`${route} returned ${response.status}`);
    const html = await response.text();
    if (!html.includes('lang="fa"') || !html.includes('dir="rtl"')) {
      throw new Error(`${route} does not render the Persian RTL document contract.`);
    }
    if (html.includes(`http://${host}:${upstreamPort}`)) {
      throw new Error(`${route} exposed the server-only backend URL.`);
    }
  }

  const proxyResponse = await fetch(`${webBase}/api/v1/smoke?probe=preserved`);
  const proxyBytes = await proxyResponse.text();
  if (!proxyResponse.ok || !queryObserved || !proxyBytes.includes(`"${decimal}"`)) {
    throw new Error("Proxy did not preserve query or exact Decimal JSON string.");
  }

  const conflict = await fetch(`${webBase}/api/v1/smoke/failure`);
  const conflictBody = await conflict.text();
  if (conflict.status !== 409 || !conflictBody.includes("intentional_conflict")) {
    throw new Error("Proxy did not preserve the non-200 status and safe error body.");
  }

  const buildManifest = await readFile(resolve(".next", "build-manifest.json"), "utf8");
  if (buildManifest.includes(`http://${host}:${upstreamPort}`)) {
    throw new Error("Backend URL leaked into a client build manifest.");
  }

  console.log("Production smoke passed: nine routes, redirect, safe proxy, and exact Decimal.");
} finally {
  nextProcess.kill();
  await close(upstream);
  await new Promise((resolvePromise) => {
    if (nextProcess.exitCode !== null) {
      resolvePromise();
      return;
    }
    nextProcess.once("exit", resolvePromise);
    setTimeout(resolvePromise, 3_000);
  });
}
