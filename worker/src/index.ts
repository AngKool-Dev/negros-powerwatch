import { ReportService, broadcastEvent, createSSEStream } from "./services";
import { Outage, CommunityReport, GeographicArea, MapAreaStatus } from "./models";
import { CONFIG, getFacebookSources } from "./config";
import { utcNow, generateId } from "./utils";
import { ACTIVE_OUTAGE_STATUSES } from "./engine";

export interface Env {
  DB: D1Database;
}

let initialized = false;

async function ensureInitialized(db: D1Database): Promise<void> {
  if (initialized) return;
  const areasCount = await db.prepare("SELECT COUNT(*) as cnt FROM geographic_areas").first();
  if ((areasCount as any).cnt === 0) {
    const areas = [
      ["Negros Oriental", "province", null, 9.8, 123.5],
      ["Siaton", "municipality", "Negros Oriental", 9.65, 123.15],
      ["Zamboanguita", "municipality", "Negros Oriental", 9.1, 123.2],
      ["Bayawan", "city", "Negros Oriental", 9.35, 122.8],
      ["Dumaguete", "city", "Negros Oriental", 9.3, 123.3],
      ["Bacong", "municipality", "Negros Oriental", 9.25, 123.3],
      ["Valencia", "municipality", "Negros Oriental", 9.25, 123.55],
      ["Dauin", "municipality", "Negros Oriental", 9.2, 123.35],
      ["Santa Catalina", "municipality", "Negros Oriental", 9.25, 123.1],
      ["Ayungon", "municipality", "Negros Oriental", 9.4, 123.2],
      ["Mabinay", "municipality", "Negros Oriental", 9.7, 123.1],
      ["Bindoy", "municipality", "Negros Oriental", 9.75, 123.1],
      ["Manjuyod", "municipality", "Negros Oriental", 9.65, 123.15],
      ["Pamplona", "municipality", "Negros Oriental", 9.55, 123.1],
      ["Tanjay", "city", "Negros Oriental", 9.5, 123.15],
    ];
    for (const [name, area_type, parent_name, lat, lon] of areas) {
      const id = generateId();
      const now = utcNow();
      await db.prepare("INSERT INTO geographic_areas (id, name, area_type, parent_id, latitude, longitude, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)")
        .bind(id, name, area_type, parent_name, lat, lon, now).run();
    }
  }

  const sourcesCount = await db.prepare("SELECT COUNT(*) as cnt FROM sources").first();
  if ((sourcesCount as any).cnt === 0) {
    const sources = [
      ["community", "community", 0.7],
      ["noreco_ii", "noreco_ii", 0.9],
      ["ngcp", "ngcp", 0.9],
    ];
    const now = utcNow();
    for (const [name, source_type, reliability] of sources) {
      const id = generateId();
      await db.prepare("INSERT INTO sources (id, name, source_type, reliability, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)")
        .bind(id, name, source_type, reliability, "unknown", now, now).run();
    }
  }
  initialized = true;
}

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
};

async function handleRequest(request: Request, env: Env): Promise<Response> {
  const url = new URL(request.url);
  const path = url.pathname;
  const method = request.method;

  if (method === "OPTIONS") {
    return new Response(null, { status: 204, headers: corsHeaders });
  }

  const service = new ReportService(env.DB);
  await ensureInitialized(env.DB);

  const jsonResponse = (body: any, status = 200) => {
    return new Response(JSON.stringify(body), {
      status,
      headers: {
        "Content-Type": "application/json",
        ...corsHeaders,
      },
    });
  };

  if (path === "/api/v1/status" && method === "GET") {
    const data = await service.getStatus();
    return jsonResponse({
      status: data.status,
      active_outages: data.active_outages,
      last_updated: data.last_updated,
      outages: data.outages,
    });
  }

  if (path === "/api/v1/outages" && method === "GET") {
    const outages = await service.getActiveOutages();
    return jsonResponse(outages);
  }

  if (path === "/api/v1/outages/active" && method === "GET") {
    const outages = await service.getActiveOutages();
    return jsonResponse(outages);
  }

  const outageMatch = path.match(/^\/api\/v1\/outages\/([^\/]+)$/);
  if (outageMatch && method === "GET") {
    const outageId = outageMatch[1];
    const outage = await service.getOutageById(outageId);
    if (!outage) {
      return jsonResponse({ detail: "Outage not found" }, 404);
    }
    return jsonResponse(outage);
  }

  if (path === "/api/v1/reports" && method === "POST") {
    const body = await request.json().catch(() => ({}));
    const clientHost = request.headers.get("CF-Connecting-IP");
    body.ip_address = clientHost || body.ip_address;
    body.session_id = body.session_id || clientHost ? `anon-${clientHost}` : "anonymous";
    const result = await service.submitReport(body);
    if (result.status === "duplicate") {
      return jsonResponse({ detail: "Duplicate report" }, 429);
    }
    return jsonResponse(result);
  }

  if (path === "/api/v1/reports/power-off" && method === "POST") {
    const body = await request.json().catch(() => ({}));
    body.power_status = "off";
    const result = await service.submitReport(body);
    return jsonResponse(result);
  }

  if (path === "/api/v1/reports/power-restored" && method === "POST") {
    const body = await request.json().catch(() => ({}));
    body.power_status = "restored";
    const result = await service.submitReport(body);
    return jsonResponse(result);
  }

  if (path === "/api/v1/scan" && method === "POST") {
    const result = await service.scanSources();
    return jsonResponse(result);
  }

  if (path === "/api/v1/admin/facebook/status" && method === "GET") {
    const status = await service.getFacebookStatus();
    return jsonResponse(status);
  }

  if (path === "/api/v1/map/reports" && method === "GET") {
    const stmt = env.DB.prepare(
      "SELECT id, latitude, longitude, timestamp, area_id, municipality, barangay FROM community_reports WHERE latitude IS NOT NULL AND longitude IS NOT NULL AND power_status = 'out'"
    );
    const { results } = await stmt.all();
    return jsonResponse(results);
  }

  if (path === "/api/v1/map/status" && method === "GET") {
    const outages = await service.getActiveOutages();
    const areaMap = new Map<string, MapAreaStatus>();
    for (const outage of outages) {
      for (const oa of outage.areas || []) {
        const areaStmt = env.DB.prepare("SELECT * FROM geographic_areas WHERE id = ?");
        const area = await areaStmt.bind(oa.area_id).first();
        if (!area) continue;
        const key = area.id;
        if (!areaMap.has(key)) {
          areaMap.set(key, {
            area_id: area.id,
            area_name: area.name,
            status: outage.status,
            confidence: outage.confidence,
            outage_id: outage.id,
            started_at: outage.started_at,
            restored_at: outage.restored_at,
            report_count: outage.report_count,
            center: area.latitude && area.longitude ? [area.latitude, area.longitude] : null,
          });
        }
      }
    }
    return jsonResponse(Array.from(areaMap.values()));
  }

  if (path === "/api/v1/events" && method === "GET") {
    const stream = createSSEStream();
    return new Response(stream, {
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        ...corsHeaders,
      },
    });
  }

  return new Response("Not Found", { status: 404, headers: corsHeaders });
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    return handleRequest(request, env);
  },

  async scheduled(event: ScheduledEvent, env: Env, ctx: ExecutionContext): Promise<void> {
    const service = new ReportService(env.DB);
    await ensureInitialized(env.DB);
    try {
      await service.scanSources();
    } catch (e) {
      console.error("Scheduled scan failed:", e);
    }
  },
};
