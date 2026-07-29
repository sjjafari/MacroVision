import { createServer } from "node:http";
import { spawn } from "node:child_process";
import { readFile, readdir } from "node:fs/promises";
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
  if (request.url === "/api/v1/smoke/redirect-relative") {
    response.writeHead(307, {
      location: "/api/v1/smoke/target?kind=relative&query=preserved",
    });
    response.end();
    return;
  }
  if (request.url === "/api/v1/smoke/redirect-absolute") {
    response.writeHead(308, {
      location: `http://${host}:${upstreamPort}/api/v1/smoke/target?kind=absolute`,
    });
    response.end();
    return;
  }
  if (request.url === "/api/v1/smoke/redirect-external") {
    response.writeHead(302, {
      location: "https://attacker.invalid/collect?secret=destination",
    });
    response.end();
    return;
  }
  if (request.url === "/api/v1/smoke/method") {
    response.writeHead(405, {
      allow: "GET, HEAD",
      "content-type": "application/json",
    });
    response.end(JSON.stringify({ error: { code: "method_not_allowed" } }));
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

  const relativeRedirect = await fetch(`${webBase}/api/v1/smoke/redirect-relative`, {
    redirect: "manual",
  });
  if (
    relativeRedirect.status !== 307 ||
    relativeRedirect.headers.get("location") !==
      "/api/v1/smoke/target?kind=relative&query=preserved"
  ) {
    throw new Error("Proxy did not safely rewrite the relative backend redirect.");
  }

  const absoluteRedirect = await fetch(`${webBase}/api/v1/smoke/redirect-absolute`, {
    redirect: "manual",
  });
  const absoluteLocation = absoluteRedirect.headers.get("location");
  if (
    absoluteRedirect.status !== 308 ||
    absoluteLocation !== "/api/v1/smoke/target?kind=absolute" ||
    absoluteLocation.includes(`${host}:${upstreamPort}`)
  ) {
    throw new Error("Proxy did not safely rewrite the absolute backend redirect.");
  }

  const externalRedirect = await fetch(`${webBase}/api/v1/smoke/redirect-external`, {
    redirect: "manual",
  });
  const externalBody = await externalRedirect.text();
  if (
    externalRedirect.status !== 502 ||
    externalRedirect.headers.has("location") ||
    externalBody.includes("attacker.invalid") ||
    externalBody.includes("secret=destination")
  ) {
    throw new Error("Proxy did not fail closed for an external backend redirect.");
  }

  const methodNotAllowed = await fetch(`${webBase}/api/v1/smoke/method`);
  if (
    methodNotAllowed.status !== 405 ||
    methodNotAllowed.headers.get("allow") !== "GET, HEAD"
  ) {
    throw new Error("Proxy did not preserve the safe Allow header on a 405 response.");
  }

  const buildManifest = await readFile(resolve(".next", "build-manifest.json"), "utf8");
  if (buildManifest.includes(`http://${host}:${upstreamPort}`)) {
    throw new Error("Backend URL leaked into a client build manifest.");
  }
  const clientAssetRoot = resolve(".next", "static");
  const clientAssets = await readdir(clientAssetRoot, { recursive: true });
  for (const asset of clientAssets.filter((name) => name.endsWith(".js"))) {
    const contents = await readFile(resolve(clientAssetRoot, asset), "utf8");
    if (contents.includes(`http://${host}:${upstreamPort}`)) {
      throw new Error(`Backend URL leaked into client asset ${asset}.`);
    }
  }

  console.log(
    "Production smoke passed: nine routes, safe redirects, 405, 409, server-only backend, and exact Decimal.",
  );
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
