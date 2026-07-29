import createClient from "openapi-fetch";

import type { paths } from "@/lib/api/generated/schema";

export const apiClient = createClient<paths>({
  baseUrl: "",
});
