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
      ["Amlan", "municipality", "Negros Oriental", 9.43154627980005, 123.18694893990009],
      ["Ayungon", "municipality", "Negros Oriental", 9.839607289571477, 123.08480007276196],
      ["Bacong", "municipality", "Negros Oriental", 9.250654493142909, 123.25088552128577],
      ["Basay", "municipality", "Negros Oriental", 9.444160756562553, 122.68098230068756],
      ["Bindoy", "municipality", "Negros Oriental", 9.767478086529453, 123.05830008617653],
      ["Dauin", "municipality", "Negros Oriental", 10.003609847111168, 123.14548395633341],
      ["Jimalalud", "municipality", "Negros Oriental", 10.003609847111168, 123.14548395633341],
      ["La Libertad", "municipality", "Negros Oriental", 10.049564189333378, 123.18171494788895],
      ["Mabinay", "municipality", "Negros Oriental", 9.71015535616005, 122.89972179920007],
      ["Manjuyod", "municipality", "Negros Oriental", 9.70574848788466, 123.06353862407698],
      ["Pamplona", "municipality", "Negros Oriental", 9.451031060272783, 123.05763238200007],
      ["San Jose", "municipality", "Negros Oriental", 9.415967594375047, 123.21815643987509],
      ["Santa Catalina", "municipality", "Negros Oriental", 9.311550231071482, 122.93805128525005],
      ["Siaton", "municipality", "Negros Oriental", 9.133264176625053, 123.06675948196883],
      ["Sibulan", "municipality", "Negros Oriental", 9.351796289000053, 123.16487132453852],
      ["Tayasan", "municipality", "Negros Oriental", 9.92719729908338, 123.11337595400005],
      ["Valencia", "municipality", "Negros Oriental", 9.29321756975005, 123.16792527241672],
      ["Vallehermoso", "municipality", "Negros Oriental", 10.348514432000059, 123.29813926362505],
      ["Zamboanguita", "municipality", "Negros Oriental", 9.172270659416725, 123.16590882383339],
      ["Bais", "city", "Negros Oriental", 9.59891786337042, 123.09013551329636],
      ["Bayawan", "city", "Negros Oriental", 9.526052842897485, 122.82501985394879],
      ["Canlaon", "city", "Negros Oriental", 10.375112780142903, 123.20902604564291],
      ["Dumaguete", "city", "Negros Oriental", 9.306345957333386, 123.29194476100007],
      ["Guihulngan", "city", "Negros Oriental", 10.231864835800055, 123.2556808341334],
      ["Tanjay", "city", "Negros Oriental", 9.506537643757625, 123.1123716034849],
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
      "SELECT id, latitude, longitude, timestamp, area_id, municipality, barangay FROM community_reports WHERE power_status IN ('out', 'off')"
    );
    const { results } = await stmt.all();
    return jsonResponse(results);
  }

  if (path === "/api/v1/map/status" && method === "GET") {
    const outages = await service.getActiveOutages();
    const areaMap = new Map<string, MapAreaStatus>();
    for (const outage of outages) {
      const outageAreas = await env.DB.prepare("SELECT * FROM outage_areas WHERE outage_id = ?").bind(outage.id).all();
      const areas = (outageAreas.results || []) as any[];
      for (const oa of areas) {
        const area = await env.DB.prepare("SELECT * FROM geographic_areas WHERE id = ?").bind(oa.area_id).first();
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
