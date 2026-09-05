import { OutageEngine } from "./engine";
import { Outage, OutageStatus, CommunityReport, Signal, Source, GeographicArea, SystemEvent } from "./models";
import { CONFIG, getFacebookSources } from "./config";
import { utcNow, generateId } from "./utils";
import { fetchFacebookSignals } from "./providers/facebook";

export class ReportService {
  private db: D1Database;
  private engine: OutageEngine;

  constructor(db: D1Database) {
    this.db = db;
    this.engine = new OutageEngine(db);
  }

  async submitReport(reportData: Record<string, any>): Promise<Record<string, any>> {
    await this.engine.ensureSources();

    const sourceStmt = this.db.prepare("SELECT * FROM sources WHERE name = 'community'");
    const source = (await sourceStmt.first()) as Source | null;
    if (!source) {
      const newSource: Source = {
        id: generateId(),
        name: "community",
        source_type: "community",
        reliability: 0.7,
        status: "unknown",
        last_seen: utcNow(),
        last_success: null,
        last_failure: null,
        latency_ms: null,
        metadata_json: null,
        created_at: utcNow(),
        updated_at: utcNow(),
      };
      const stmt = this.db.prepare("INSERT INTO sources (id, name, source_type, reliability, status, last_seen, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)");
      await stmt.bind(newSource.id, newSource.name, newSource.source_type, newSource.reliability, newSource.status, newSource.last_seen, newSource.created_at, newSource.updated_at).run();
    }

    const sessionId = reportData.session_id || "anonymous";
    const cutoff = new Date(Date.now() - CONFIG.reportDuplicateWindowSeconds * 1000).toISOString();
    const recentStmt = this.db.prepare(
      "SELECT id FROM community_reports WHERE session_id = ? AND power_status = ? AND created_at >= ? LIMIT 1"
    );
    const recent = await recentStmt.bind(sessionId, reportData.power_status, cutoff).first();
    if (recent) {
      return { status: "duplicate", existing_report_id: recent.id as string };
    }

    let areaId = reportData.area_id || null;
    let areaLat = reportData.latitude ?? null;
    let areaLng = reportData.longitude ?? null;

    if (!areaId && reportData.municipality) {
      const areaStmt = this.db.prepare("SELECT id, latitude, longitude FROM geographic_areas WHERE name LIKE ? AND area_type = 'municipality' LIMIT 1");
      const area = await areaStmt.bind(`%${reportData.municipality}%`).first();
      if (area) {
        areaId = area.id as string;
        if (areaLat === null) areaLat = area.latitude as number | null;
        if (areaLng === null) areaLng = area.longitude as number | null;
      }
    }

    const report: CommunityReport = {
      id: generateId(),
      outage_id: null,
      session_id: sessionId,
      timestamp: utcNow(),
      latitude: areaLat,
      longitude: areaLng,
      area_id: areaId,
      power_status: reportData.power_status || "unknown",
      municipality: reportData.municipality || null,
      barangay: reportData.barangay || null,
      notes: reportData.notes || null,
      device_info: reportData.device_info || null,
      ip_address: reportData.ip_address || null,
      created_at: utcNow(),
    };

    const reportStmt = this.db.prepare(
      "INSERT INTO community_reports (id, outage_id, session_id, timestamp, latitude, longitude, area_id, power_status, municipality, barangay, notes, device_info, ip_address, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
    );
    await reportStmt.bind(
      report.id, report.outage_id, report.session_id, report.timestamp,
      report.latitude, report.longitude, report.area_id, report.power_status,
      report.municipality, report.barangay, report.notes, report.device_info, report.ip_address, report.created_at
    ).run();

    const outage = await this.engine.processCommunityReport(report);

    const event: SystemEvent = {
      id: generateId(),
      event_type: "REPORT_RECEIVED",
      message: `Community report received: ${report.power_status}`,
      outage_id: outage?.id || null,
      source: "community",
      metadata_json: `{"report_id": "${report.id}"}`,
      created_at: utcNow(),
    };
    const eventStmt = this.db.prepare("INSERT INTO system_events (id, event_type, message, outage_id, source, metadata_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)");
    await eventStmt.bind(event.id, event.event_type, event.message, event.outage_id, event.source, event.metadata_json, event.created_at).run();

    broadcastEvent({
      type: "report_received",
      report_id: report.id,
      outage_id: outage?.id || null,
      outage_status: outage?.status || null,
    });

    return {
      status: "accepted",
      report_id: report.id,
      outage_id: outage?.id || null,
      outage_status: outage?.status || null,
    };
  }

  async getStatus(): Promise<Record<string, any>> {
    await this.engine.ensureSources();
    const activeOutages = await this.engine.getActiveOutages();
    return {
      status: "operational",
      active_outages: activeOutages.length,
      outages: activeOutages,
      last_updated: utcNow(),
    };
  }

  async getActiveOutages(): Promise<Outage[]> {
    await this.engine.ensureSources();
    return this.engine.getActiveOutages();
  }

  async getOutageById(outageId: string): Promise<Outage | null> {
    await this.engine.ensureSources();
    return this.engine.getOutageById(outageId);
  }

  async closeStale(): Promise<Outage[]> {
    await this.engine.ensureSources();
    return this.engine.closeStaleOutages();
  }

  async scanSources(): Promise<{ total_signals: number; providers: Record<string, { signals_found: number; status: string }> }> {
    await this.engine.ensureSources();
    const { signals, results } = await fetchFacebookSignals(this.db);
    for (const signal of signals) {
      await this.engine.processSignal(signal);
    }
    broadcastEvent({
      type: "scan_complete",
      total_signals: signals.length,
      providers: results,
    });
    return {
      total_signals: signals.length,
      providers: results,
    };
  }

  async getFacebookStatus(): Promise<Record<string, any>> {
    await this.engine.ensureSources();
    const sources = getFacebookSources();
    const sourceStatuses = sources.map((s) => ({
      name: s.name,
      page_id: s.page_id,
      enabled: s.enabled !== false,
    }));

    const accessToken = CONFIG.facebookAccessToken;
    let health = false;
    if (accessToken) {
      try {
        const response = await fetch(`https://graph.facebook.com/v18.0/me?access_token=${encodeURIComponent(accessToken)}`, { signal: AbortSignal.timeout(10000) });
        health = response.ok;
      } catch {
        health = false;
      }
    }

    return {
      enabled: CONFIG.facebookEnabled,
      access_token_configured: !!accessToken,
      poll_interval_minutes: CONFIG.facebookPollIntervalMinutes,
      sources: sourceStatuses,
      last_success: null,
      last_error: null,
      health,
    };
  }
}

const sseClients: Set<ReadableStreamDefaultController> = new Set();

export function broadcastEvent(data: Record<string, any>): void {
  const message = `data: ${JSON.stringify(data)}\n\n`;
  for (const controller of sseClients) {
    try {
      controller.enqueue(new TextEncoder().encode(message));
    } catch {
      sseClients.delete(controller);
    }
  }
}

export function createSSEStream(): ReadableStream {
  const stream = new ReadableStream({
    start(controller) {
      sseClients.add(controller);
      controller.enqueue(new TextEncoder().encode(`: connected\n\n`));
    },
    cancel() {
      sseClients.delete(controller as ReadableStreamDefaultController);
    },
  });
  return stream;
}
