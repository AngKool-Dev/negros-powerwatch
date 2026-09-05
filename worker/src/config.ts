export const CONFIG = {
  appName: "Negros PowerWatch",
  apiPrefix: "/api/v1",
  reportDuplicateWindowSeconds: 300,
  reportMinReports: 3,
  reportTimeWindowSeconds: 600,
  reportRadiusKm: 5.0,
  staleSignalSeconds: 3600,
  restorationWindowSeconds: 300,
  sseRetryIntervalMs: 5000,
  facebookEnabled: (env => env.FACEBOOK_ENABLED !== "false")(globalThis as any),
  facebookAccessToken: (env => env.FACEBOOK_ACCESS_TOKEN || "")(globalThis as any),
  facebookPollIntervalMinutes: 1,
  facebookSourcesJson: (env => env.FACEBOOK_SOURCES || "[]")(globalThis as any),
  get facebookSources(): any[] {
    try {
      return JSON.parse(this.facebookSourcesJson);
    } catch {
      return [];
    }
  },
  get facebookSourceNames(): string[] {
    return this.facebookSources.map((s: any) => s.get("name") || s.get("page_id") || s.get("url") || "unknown");
  },
};

export function getFacebookSources(): any[] {
  try {
    return JSON.parse((globalThis as any).FACEBOOK_SOURCES || "[]");
  } catch {
    return [];
  }
}

export function getFacebookSourceNames(): string[] {
  return getFacebookSources().map((s: any) => s.name || s.page_id || s.url || "unknown");
}
