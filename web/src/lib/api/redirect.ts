export function rewriteUpstreamRedirect(
  location: string,
  backendRequestUrl: URL,
  backendBaseUrl: URL,
): string | null {
  let target: URL;
  try {
    target = new URL(location, backendRequestUrl);
  } catch {
    return null;
  }

  if (target.username || target.password || target.origin !== backendRequestUrl.origin) {
    return null;
  }

  const basePath = backendBaseUrl.pathname === "/" ? "" : backendBaseUrl.pathname;
  const apiBoundary = `${basePath}/api/v1`;
  if (
    (target.pathname !== apiBoundary && !target.pathname.startsWith(`${apiBoundary}/`))
  ) {
    return null;
  }

  const browserPath = target.pathname.slice(apiBoundary.length);
  return `/api/v1${browserPath}${target.search}${target.hash}`;
}
