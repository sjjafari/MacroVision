import "server-only";

const BACKEND_ENVIRONMENT_VARIABLE = "MACROVISION_BACKEND_URL";

export function getBackendUrl(): URL {
  const rawValue = process.env[BACKEND_ENVIRONMENT_VARIABLE];
  if (!rawValue) {
    throw new Error(`${BACKEND_ENVIRONMENT_VARIABLE} is not configured`);
  }

  const url = new URL(rawValue);
  if (!["http:", "https:"].includes(url.protocol)) {
    throw new Error(`${BACKEND_ENVIRONMENT_VARIABLE} must use HTTP or HTTPS`);
  }
  if (url.username || url.password) {
    throw new Error(`${BACKEND_ENVIRONMENT_VARIABLE} must not contain credentials`);
  }
  if (url.search || url.hash) {
    throw new Error(`${BACKEND_ENVIRONMENT_VARIABLE} must not contain a query or fragment`);
  }

  url.pathname = url.pathname.replace(/\/+$/, "") || "/";
  return url;
}
