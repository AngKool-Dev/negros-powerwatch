import { CONFIG, getFacebookSources } from "../config";
import { Signal, Source, SourceStatus, SourceType } from "../models";

const NEGROS_ORIENTAL_MUNICIPALITIES = [
  "amlan", "ayungon", "bacong", "basay", "bindoy", "payabon", "dauin", "jimalalud",
  "la libertad", "mabinay", "manjuyod", "pamplona", "san jose",
  "santa catalina", "siaton", "sibulan", "tayasan", "valencia", "luzuriaga",
  "vallehermoso", "zamboanguita", "dumaguete", "dumaguete city",
  "bais", "bais city", "canlaon", "canlaon city",
  "guihulngan", "guihulngan city", "tanjay", "tanjay city",
  "bayawan", "bayawan city", "negros oriental", "negros",
];

const LOCATION_ALIASES: Record<string, string> = {
  ayquitan: "amlan",
  ayuquitan: "amlan",
  payabon: "bindoy",
  luzuriaga: "valencia",
};

const OUTAGE_KEYWORDS: Record<string, string[]> = {
  "+5": [
    "brownout", "brown out", "power outage", "power interruption", "power failure",
    "power loss", "no electricity", "no electric", "no power", "electricity gone",
    "kuryente", "walay kuryente", "wala'y kuryente", "walay suga", "walay power",
    "naputol ang kuryente", "naputol kuryente", "naputol among kuryente",
    "wala mi kuryente", "wala kami kuryente", "walang kuryente",
    "sudden brownout", "sudden power outage", "unexpected brownout", "unexpected outage",
    "tripped", "transformer explosion", "transformer problem", "transformer busted",
    "naputol nga linya", "naputol ang linya", "nahugno poste",
    "sunog", "electrical fire", "spark",
  ],
  "+3": [
    "kuryente", "linya", "poste", "pundok",
    "brownout diri", "brownout sa amo", "brownout sa amoa",
    "wala gihapon kuryente", "wala gihapon power",
    "dugay na brownout", "pila na ka oras walay kuryente",
    "3 hours na walay kuryente", "2 hours na walay kuryente",
    "1 hour na walay kuryente",
  ],
  "+1": [
    "scheduled brownout", "scheduled outage", "planned outage",
    "power interruption advisory", "brownout schedule", "brownout advisory",
    "outage advisory", "power advisory", "maintenance", "maintenance shutdown",
    "line maintenance", "repair", "repair work", "emergency maintenance",
    "advisory", "schedule",
  ],
  "-5": [
    "kuryente nibalik", "nibalik ang kuryente", "nibalik na ang kuryente",
    "may kuryente na", "naa nay kuryente", "naa na kuryente", "naay kuryente",
    "power restored", "electricity restored", "power back", "kuryente balik",
    "siga na", "nibalik na", "naa na",
  ],
};

const RESTORATION_KEYWORDS = new Set([
  "kuryente nibalik", "nibalik ang kuryente", "nibalik na ang kuryente",
  "may kuryente na", "naa nay kuryente", "naa na kuryente", "naay kuryente",
  "power restored", "electricity restored", "power back", "kuryente balik",
  "siga na", "nibalik na", "naa na",
]);

const PLANNED_KEYWORDS = new Set([
  "scheduled brownout", "scheduled outage", "planned outage",
  "power interruption advisory", "brownout schedule", "brownout advisory",
  "outage advisory", "power advisory", "maintenance", "maintenance shutdown",
  "line maintenance", "repair", "repair work", "emergency maintenance",
]);

export function scorePost(text: string): { score: number; isRestoration: boolean; isPlanned: boolean } {
  const lower = text.toLowerCase();
  let score = 0;
  let isRestoration = false;
  let isPlanned = false;

  for (const keyword of RESTORATION_KEYWORDS) {
    if (lower.includes(keyword)) {
      isRestoration = true;
      score -= 5;
      break;
    }
  }

  for (const keyword of PLANNED_KEYWORDS) {
    if (lower.includes(keyword)) {
      isPlanned = true;
      score += 1;
    }
  }

  for (const [scoreVal, keywords] of Object.entries(OUTAGE_KEYWORDS)) {
    const val = parseInt(scoreVal);
    for (const keyword of keywords) {
      if (lower.includes(keyword)) {
        score += val;
      }
    }
  }

  return { score, isRestoration, isPlanned };
}

export function detectLocation(text: string): { area: string | null; barangay: string | null } {
  let lower = text.toLowerCase();
  let foundMuni: string | null = null;
  let foundBarangay: string | null = null;

  for (const [alias, canonical] of Object.entries(LOCATION_ALIASES)) {
    if (lower.includes(alias)) {
      lower = lower.replace(alias, canonical);
    }
  }

  for (const muni of NEGROS_ORIENTAL_MUNICIPALITIES) {
    if (lower.includes(muni)) {
      foundMuni = muni.replace(/\b\w/g, (c) => c.toUpperCase());
      break;
    }
  }

  const barangayMatch = lower.match(/(?:barangay|brgy\.?|brgy|purok|sitio)\s+([a-z0-9 ]+)/);
  if (barangayMatch) {
    foundBarangay = barangayMatch[1].trim().replace(/\b\w/g, (c) => c.toUpperCase());
  }

  return { area: foundMuni, barangay: foundBarangay };
}

export async function fetchFacebookSignals(db: D1Database): Promise<{ signals: Signal[]; results: Record<string, { signalsFound: number; status: string }> }> {
  const useMock = (globalThis as any).FACEBOOK_MOCK === 'true';
  const sources = getFacebookSources();
  const results: Record<string, { signalsFound: number; status: string }> = {};
  let totalSignals = 0;
  const allSignals: Signal[] = [];

  const sourceStmt = db.prepare("SELECT * FROM sources WHERE name = ?");
  const areaStmt = db.prepare("SELECT * FROM geographic_areas WHERE name LIKE ? AND area_type = 'municipality' LIMIT 1");
  const existingSignalStmt = db.prepare("SELECT id FROM signals WHERE source_id = ? AND metadata_json LIKE ? LIMIT 1");
  const insertSignalStmt = db.prepare(
    "INSERT INTO signals (id, source_id, signal_type, timestamp, latitude, longitude, area_id, status, confidence, metadata_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
  );
  const upsertSourceStmt = db.prepare(
    "INSERT INTO sources (id, name, source_type, reliability, status, last_seen, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(name) DO UPDATE SET last_seen = excluded.last_seen, status = excluded.status, updated_at = excluded.updated_at"
  );
  const updateSourceStmt = db.prepare("UPDATE sources SET last_seen = ?, status = ? WHERE id = ?");

  const accessToken = CONFIG.facebookAccessToken;
  const enabled = CONFIG.facebookEnabled;

  for (const sourceConfig of sources) {
    const sourceName = sourceConfig.name || sourceConfig.page_id || sourceConfig.url || "unknown";
    results[sourceName] = { signalsFound: 0, status: "ok" };

    if (!sourceConfig.enabled || !enabled) continue;

    const pageId = sourceConfig.page_id || sourceConfig.url?.replace(/\/$/, "").split("/").pop() || "";
    if (!pageId) {
      results[sourceName] = { signalsFound: 0, status: "no_page_id" };
      continue;
    }

    if (!accessToken) {
      results[sourceName] = { signalsFound: 0, status: "no_access_token" };
      continue;
    }

    try {
      const url = `https://graph.facebook.com/v18.0/${pageId}/posts?fields=${encodeURIComponent("id,message,created_time,permalink_url,from")}&limit=${sourceConfig.limit || 20}&access_token=${encodeURIComponent(accessToken)}`;
      const response = await fetch(url);
      if (!response.ok) {
        if (response.status === 429) {
          results[sourceName] = { signalsFound: 0, status: "rate_limited" };
          continue;
        }
        if (response.status === 401 || response.status === 403) {
          results[sourceName] = { signalsFound: 0, status: "auth_failed" };
          continue;
        }
        results[sourceName] = { signalsFound: 0, status: `api_error_${response.status}` };
        continue;
      }

      const data = await response.json();
      const posts = data.data || [];

      let source = await sourceStmt.bind(sourceName).first() as Source | null;
      if (!source) {
        const newId = crypto.randomUUID();
        const now = new Date().toISOString();
        source = {
          id: newId,
          name: sourceName,
          source_type: "community",
          reliability: 0.5,
          status: "unknown",
          last_seen: now,
          last_success: now,
          last_failure: null,
          latency_ms: null,
          metadata_json: null,
          created_at: now,
          updated_at: now,
        };
        await upsertSourceStmt.bind(source.id, source.name, source.source_type, source.reliability, source.status, source.last_seen, source.created_at, source.updated_at).run();
      } else {
        const now = new Date().toISOString();
        await updateSourceStmt.bind(now, "healthy", source.id).run();
      }

      for (const post of posts) {
        const message = post.message || "";
        if (!message) continue;

        const { score, isRestoration, isPlanned } = scorePost(message);
        if (score < 5 && !isRestoration) continue;

        const { area, barangay } = detectLocation(message);

        let areaRow = null;
        if (area) {
          areaRow = await areaStmt.bind(`%${area}%`).first();
        }

        const sourceId = source.id;
        const metadata = {
          raw_text: message.slice(0, 1000),
          score,
          barangay,
          source_url: post.permalink_url || "",
          source_id: post.id || "",
          page_id: post.from?.id || pageId,
          author: post.from?.name || "",
          source_name: sourceName,
        };

        const existing = await existingSignalStmt.bind(sourceId, `%"source_id": "${post.id || ""}"`).first();
        if (existing) continue;

        const confidence = Math.min(0.95, Math.max(0.2, score / 15));
        const status = isRestoration ? "restored" : isPlanned ? "planned" : "out";

        const signal: Signal = {
          id: crypto.randomUUID(),
          outage_id: null,
          source_id: sourceId,
          signal_type: "scraper",
          timestamp: new Date(post.created_time || Date.now()).toISOString(),
          latitude: null,
          longitude: null,
          area_id: areaRow?.id || null,
          status,
          confidence,
          metadata_json: JSON.stringify(metadata),
          processed: false,
          created_at: new Date().toISOString(),
        };

        await insertSignalStmt.bind(
          signal.id, signal.source_id, signal.signal_type, signal.timestamp,
          signal.latitude, signal.longitude, signal.area_id, signal.status,
          signal.confidence, signal.metadata_json, signal.created_at
        ).run();

        allSignals.push(signal);
        totalSignals++;
      }

      results[sourceName] = { signalsFound: allSignals.filter((s) => s.source_id === sourceId).length, status: "ok" };
    } catch (e: any) {
      results[sourceName] = { signalsFound: 0, status: `error: ${e.message}` };
    }
  }

  return { signals: allSignals, results };
}
