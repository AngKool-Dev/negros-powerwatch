import { Outage, OutageArea, Signal, Source, GeographicArea, SystemEvent, OutageStatus, SignalType, SourceType, SourceStatus, CommunityReport } from "./models";
import { generateId, utcNow, parseDate, isActiveStatus, ACTIVE_OUTAGE_STATUSES } from "./utils";
import { CONFIG, getFacebookSources } from "./config";

export class OutageEngine {
  private db: D1Database;
  private initialized = false;

  constructor(db: D1Database) {
    this.db = db;
  }

  async ensureSources(): Promise<void> {
    if (this.initialized) return;
    const defaultSources = [
      { name: "community", source_type: "community" as SourceType, reliability: 0.7 },
      { name: "noreco_ii", source_type: "noreco_ii" as SourceType, reliability: 0.9 },
      { name: "ngcp", source_type: "ngcp" as SourceType, reliability: 0.9 },
    ];
    for (const ds of defaultSources) {
      const existing = await this.getSource(ds.name);
      if (!existing) {
        const source: Source = {
          id: generateId(),
          name: ds.name,
          source_type: ds.source_type,
          reliability: ds.reliability,
          status: "unknown",
          last_seen: null,
          last_success: null,
          last_failure: null,
          latency_ms: null,
          metadata_json: null,
          created_at: utcNow(),
          updated_at: utcNow(),
        };
        const stmt = this.db.prepare("INSERT INTO sources (id, name, source_type, reliability, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)");
        await stmt.bind(source.id, source.name, source.source_type, source.reliability, source.status, source.created_at, source.updated_at).run();
      }
    }
    this.initialized = true;
  }

  async getSource(name: string): Promise<Source | null> {
    const stmt = this.db.prepare("SELECT * FROM sources WHERE name = ?");
    const result = await stmt.bind(name).first();
    if (!result) return null;
    return result as Source;
  }

  async findActiveOutageForArea(areaId: string): Promise<Outage | null> {
    const stmt = this.db.prepare(
      `SELECT o.* FROM outages o
       JOIN outage_areas oa ON o.id = oa.outage_id
       WHERE oa.area_id = ? AND o.status IN (?, ?, ?, ?, ?)
       ORDER BY o.created_at DESC LIMIT 1`
    );
    const result = await stmt.bind(areaId, ...ACTIVE_OUTAGE_STATUSES).first();
    if (!result) return null;
    return result as Outage;
  }

  async findActiveOutageNearby(latitude: number, longitude: number, radiusKm: number): Promise<Outage | null> {
    const stmt = this.db.prepare(
      `SELECT DISTINCT o.* FROM outages o
       JOIN outage_areas oa ON o.id = oa.outage_id
       JOIN geographic_areas ga ON oa.area_id = ga.id
       WHERE o.status IN (?, ?, ?, ?, ?)
       AND ga.latitude IS NOT NULL AND ga.longitude IS NOT NULL`
    );
    const { results } = await stmt.bind(...ACTIVE_OUTAGE_STATUSES).all();
    for (const outage of results as Outage[]) {
      const areas = await this.getOutageAreas(outage.id);
      for (const oa of areas) {
        const area = await this.getGeographicArea(oa.area_id);
        if (area && area.latitude !== null && area.longitude !== null) {
          if (this.isWithinRadius(latitude, longitude, area.latitude, area.longitude, radiusKm)) {
            return outage;
          }
        }
      }
    }
    return null;
  }

  async getOutageAreas(outageId: string): Promise<OutageArea[]> {
    const stmt = this.db.prepare("SELECT * FROM outage_areas WHERE outage_id = ?");
    const { results } = await stmt.bind(outageId).all();
    return results as OutageArea[];
  }

  async getGeographicArea(id: string): Promise<GeographicArea | null> {
    const stmt = this.db.prepare("SELECT * FROM geographic_areas WHERE id = ?");
    const result = await stmt.bind(id).first();
    if (!result) return null;
    return result as GeographicArea;
  }

  isWithinRadius(lat1: number, lon1: number, lat2: number, lon2: number, radiusKm: number): boolean {
    const R = 6371.0;
    const phi1 = (lat1 * Math.PI) / 180;
    const phi2 = (lat2 * Math.PI) / 180;
    const dphi = ((lat2 - lat1) * Math.PI) / 180;
    const dlambda = ((lon2 - lon1) * Math.PI) / 180;
    const a = Math.sin(dphi / 2) ** 2 + Math.cos(phi1) * Math.cos(phi2) * Math.sin(dlambda / 2) ** 2;
    const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
    return R * c <= radiusKm;
  }

  async processCommunityReport(report: CommunityReport): Promise<Outage | null> {
    const now = utcNow();
    let source = await this.getSource("community");
    if (!source) {
      source = {
        id: generateId(),
        name: "community",
        source_type: "community",
        reliability: 0.7,
        status: "unknown",
        last_seen: now,
        last_success: null,
        last_failure: null,
        latency_ms: null,
        metadata_json: null,
        created_at: now,
        updated_at: now,
      };
      const stmt = this.db.prepare("INSERT INTO sources (id, name, source_type, reliability, status, last_seen, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)");
      await stmt.bind(source.id, source.name, source.source_type, source.reliability, source.status, source.last_seen, source.created_at, source.updated_at).run();
    } else {
      source.last_seen = now;
      const updateStmt = this.db.prepare("UPDATE sources SET last_seen = ?, updated_at = ? WHERE id = ?");
      await updateStmt.bind(now, now, source.id).run();
    }

    let outage: Outage | null = null;
    if (report.area_id) {
      outage = await this.findActiveOutageForArea(report.area_id);
    }
    if (!outage && report.latitude !== null && report.longitude !== null) {
      outage = await this.findActiveOutageNearby(report.latitude, report.longitude, CONFIG.reportRadiusKm);
    }

    if (report.power_status === "off" || report.power_status === "out") {
      if (!outage) {
        outage = {
          id: generateId(),
          status: "possible",
          confidence: 0,
          report_count: 1,
          cause: null,
          notes: null,
          first_signal_at: report.timestamp,
          detected_at: null,
          official_confirmed_at: null,
          started_at: report.timestamp,
          estimated_restore_at: null,
          restored_at: null,
          closed_at: null,
          created_at: now,
          updated_at: now,
        };
        const insertOutage = this.db.prepare(
          "INSERT INTO outages (id, status, confidence, report_count, first_signal_at, started_at, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
        );
        await insertOutage.bind(outage.id, outage.status, outage.confidence, outage.report_count, outage.first_signal_at, outage.started_at, outage.created_at, outage.updated_at).run();

        if (report.area_id) {
          const oaStmt = this.db.prepare("INSERT INTO outage_areas (id, outage_id, area_id, created_at) VALUES (?, ?, ?, ?)");
          await oaStmt.bind(generateId(), outage.id, report.area_id, now).run();
        }

        const signal: Signal = {
          id: generateId(),
          outage_id: outage.id,
          source_id: source.id,
          signal_type: "community_report",
          timestamp: report.timestamp,
          latitude: report.latitude,
          longitude: report.longitude,
          area_id: report.area_id,
          status: "out",
          confidence: 0.1,
          metadata_json: `{"report_id": "${report.id}"}`,
          processed: true,
          created_at: now,
        };
        const sigStmt = this.db.prepare(
          "INSERT INTO signals (id, outage_id, source_id, signal_type, timestamp, latitude, longitude, area_id, status, confidence, metadata_json, processed, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        );
        await sigStmt.bind(signal.id, signal.outage_id, signal.source_id, signal.signal_type, signal.timestamp, signal.latitude, signal.longitude, signal.area_id, signal.status, signal.confidence, signal.metadata_json, signal.processed ? 1 : 0, signal.created_at).run();
      } else {
        outage.report_count += 1;
        outage.started_at = outage.started_at && report.timestamp < outage.started_at ? report.timestamp : outage.started_at;
        outage.first_signal_at = outage.first_signal_at && report.timestamp < outage.first_signal_at ? report.timestamp : outage.first_signal_at;

        const existingAreas = await this.getOutageAreas(outage.id);
        const hasArea = existingAreas.some((a) => a.area_id === report.area_id);
        if (report.area_id && !hasArea) {
          const oaStmt = this.db.prepare("INSERT INTO outage_areas (id, outage_id, area_id, created_at) VALUES (?, ?, ?, ?)");
          await oaStmt.bind(generateId(), outage.id, report.area_id, now).run();
        }

        const signal: Signal = {
          id: generateId(),
          outage_id: outage.id,
          source_id: source.id,
          signal_type: "community_report",
          timestamp: report.timestamp,
          latitude: report.latitude,
          longitude: report.longitude,
          area_id: report.area_id,
          status: "out",
          confidence: 0.1,
          metadata_json: `{"report_id": "${report.id}"}`,
          processed: true,
          created_at: now,
        };
        const sigStmt = this.db.prepare(
          "INSERT INTO signals (id, outage_id, source_id, signal_type, timestamp, latitude, longitude, area_id, status, confidence, metadata_json, processed, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        );
        await sigStmt.bind(signal.id, signal.outage_id, signal.source_id, signal.signal_type, signal.timestamp, signal.latitude, signal.longitude, signal.area_id, signal.status, signal.confidence, signal.metadata_json, signal.processed ? 1 : 0, signal.created_at).run();
      }

      await this.updateOutageConfidence(outage);
      await this.transitionStatus(outage, now);
      await this.updateOutage(outage);
    } else if (report.power_status === "on" || report.power_status === "restored") {
      if (outage && (outage.status === "possible" || outage.status === "detected" || outage.status === "community_confirmed" || outage.status === "officially_confirmed" || outage.status === "restoring")) {
        const nowDate = new Date(now);
        const restoredDate = outage.restored_at ? new Date(outage.restored_at) : null;
        if (!restoredDate || (nowDate.getTime() - restoredDate.getTime()) < CONFIG.restorationWindowSeconds * 1000) {
          outage.restored_at = report.timestamp;
        }
        await this.transitionStatus(outage, now);
        await this.updateOutage(outage);
      }
    }

    return outage;
  }

  async processSignal(signal: Signal): Promise<Outage | null> {
    const now = utcNow();
    const source = await this.getSource(signal.source_id);
    if (!source) {
      const newSource: Source = {
        id: generateId(),
        name: signal.source_id,
        source_type: "community",
        reliability: 0.5,
        status: "unknown",
        last_seen: now,
        last_success: null,
        last_failure: null,
        latency_ms: null,
        metadata_json: null,
        created_at: now,
        updated_at: now,
      };
      const stmt = this.db.prepare("INSERT INTO sources (id, name, source_type, reliability, status, last_seen, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)");
      await stmt.bind(newSource.id, newSource.name, newSource.source_type, newSource.reliability, newSource.status, newSource.last_seen, newSource.created_at, newSource.updated_at).run();
    } else {
      source.last_seen = now;
      const updateStmt = this.db.prepare("UPDATE sources SET last_seen = ?, updated_at = ? WHERE id = ?");
      await updateStmt.bind(now, now, source.id).run();
    }

    let outage: Outage | null = null;
    if (signal.outage_id) {
      const stmt = this.db.prepare("SELECT * FROM outages WHERE id = ?");
      const result = await stmt.bind(signal.outage_id).first();
      if (result) outage = result as Outage;
    }

    if (!outage && signal.area_id) {
      outage = await this.findActiveOutageForArea(signal.area_id);
    }

    if (!outage && signal.latitude !== null && signal.longitude !== null) {
      outage = await this.findActiveOutageNearby(signal.latitude, signal.longitude, CONFIG.reportRadiusKm);
    }

    if (!outage && signal.status === "out") {
      outage = {
        id: generateId(),
        status: "possible",
        confidence: 0,
        report_count: 0,
        cause: null,
        notes: null,
        first_signal_at: signal.timestamp,
        detected_at: null,
        official_confirmed_at: null,
        started_at: signal.timestamp,
        estimated_restore_at: null,
        restored_at: null,
        closed_at: null,
        created_at: now,
        updated_at: now,
      };
      const insertOutage = this.db.prepare(
        "INSERT INTO outages (id, status, confidence, report_count, first_signal_at, started_at, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
      );
      await insertOutage.bind(outage.id, outage.status, outage.confidence, outage.report_count, outage.first_signal_at, outage.started_at, outage.created_at, outage.updated_at).run();
    }

    if (outage) {
      signal.outage_id = outage.id;
      signal.processed = true;

      if (!outage.first_signal_at || signal.timestamp < outage.first_signal_at) {
        outage.first_signal_at = signal.timestamp;
      }
      if (!outage.started_at || signal.timestamp < outage.started_at) {
        outage.started_at = signal.timestamp;
      }

      if (signal.area_id) {
        const existing = await this.getOutageAreas(outage.id);
        const hasArea = existing.some((a) => a.area_id === signal.area_id);
        if (!hasArea) {
          const oaStmt = this.db.prepare("INSERT INTO outage_areas (id, outage_id, area_id, created_at) VALUES (?, ?, ?, ?)");
          await oaStmt.bind(generateId(), outage.id, signal.area_id, now).run();
        }
      }

      if (signal.signal_type === "official_advisory") {
        outage.official_confirmed_at = now;
      }

      await this.updateOutageConfidence(outage);
      await this.transitionStatus(outage, now);
      await this.updateOutage(outage);
    }

    const sigStmt = this.db.prepare(
      "INSERT INTO signals (id, outage_id, source_id, signal_type, timestamp, latitude, longitude, area_id, status, confidence, metadata_json, processed, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
    );
    await sigStmt.bind(signal.id, signal.outage_id, signal.source_id, signal.signal_type, signal.timestamp, signal.latitude, signal.longitude, signal.area_id, signal.status, signal.confidence, signal.metadata_json, signal.processed ? 1 : 0, signal.created_at).run();

    return outage;
  }

  async updateOutageConfidence(outage: Outage): Promise<void> {
    const sigStmt = this.db.prepare("SELECT * FROM signals WHERE outage_id = ?");
    const sigResult = await sigStmt.bind(outage.id).all();
    const signals = sigResult.results as Signal[];

    const repStmt = this.db.prepare("SELECT * FROM community_reports WHERE outage_id = ?");
    const repResult = await repStmt.bind(outage.id).all();
    const reports = repResult.results as CommunityReport[];

    const reportCount = outage.report_count || 0;
    let baseConfidence = 0;
    if (reportCount >= 20) baseConfidence = 0.95;
    else if (reportCount >= 10) baseConfidence = 0.85;
    else if (reportCount >= 5) baseConfidence = 0.70;
    else if (reportCount >= 3) baseConfidence = 0.55;
    else if (reportCount >= 1) baseConfidence = 0.30;

    const uniqueAreas = new Set(reports.filter((r) => r.area_id).map((r) => r.area_id)).size;
    if (uniqueAreas >= 3) baseConfidence = Math.min(1.0, baseConfidence + 0.10);
    else if (uniqueAreas >= 2) baseConfidence = Math.min(1.0, baseConfidence + 0.05);

    const hasOfficial = signals.some((s) => s.signal_type === "official_advisory");
    if (hasOfficial) baseConfidence = Math.min(1.0, baseConfidence + 0.15);

    outage.confidence = Math.round(Math.min(1.0, Math.max(0.0, baseConfidence)) * 100) / 100;
    const updateStmt = this.db.prepare("UPDATE outages SET confidence = ? WHERE id = ?");
    await updateStmt.bind(outage.confidence, outage.id).run();
  }

  async transitionStatus(outage: Outage, now: string): Promise<void> {
    const sigStmt = this.db.prepare("SELECT * FROM signals WHERE outage_id = ?");
    const sigResult = await sigStmt.bind(outage.id).all();
    const signals = sigResult.results as Signal[];
    const hasOfficial = signals.some((s) => s.signal_type === "official_advisory");

    if (outage.status === "possible") {
      if (outage.report_count >= CONFIG.reportMinReports || hasOfficial) {
        outage.status = hasOfficial ? "officially_confirmed" : "detected";
        outage.detected_at = now;
        if (hasOfficial) outage.official_confirmed_at = now;
        await this.logEvent("OUTAGE_DETECTED", outage);
      } else {
        return;
      }
    }

    if (outage.status === "detected") {
      if (outage.report_count >= 5 || hasOfficial) {
        outage.status = hasOfficial ? "officially_confirmed" : "community_confirmed";
        if (hasOfficial) outage.official_confirmed_at = now;
        await this.logEvent("OUTAGE_COMMUNITY_CONFIRMED", outage);
      }
    }

    if (["possible", "community_confirmed", "officially_confirmed", "detected"].includes(outage.status)) {
      if (outage.restored_at !== null) {
        outage.status = "restoring";
        await this.logEvent("OUTAGE_RESTORING", outage);
      }
    }

    if (outage.status === "restoring") {
      const restoredDate = outage.restored_at ? new Date(outage.restored_at) : null;
      const nowDate = new Date(now);
      if (restoredDate && (nowDate.getTime() - restoredDate.getTime()) >= 60000) {
        outage.status = "restored";
        outage.closed_at = now;
        await this.logEvent("OUTAGE_RESTORED", outage);
      }
    }

    const updateStmt = this.db.prepare("UPDATE outages SET status = ?, detected_at = ?, official_confirmed_at = ?, closed_at = ? WHERE id = ?");
    await updateStmt.bind(outage.status, outage.detected_at, outage.official_confirmed_at, outage.closed_at, outage.id).run();
  }

  async logEvent(eventType: string, outage: Outage): Promise<void> {
    const event: SystemEvent = {
      id: generateId(),
      event_type: eventType,
      message: `Outage ${outage.id} transitioned to ${outage.status}`,
      outage_id: outage.id,
      source: "engine",
      metadata_json: null,
      created_at: utcNow(),
    };
    const stmt = this.db.prepare("INSERT INTO system_events (id, event_type, message, outage_id, source, created_at) VALUES (?, ?, ?, ?, ?, ?)");
    await stmt.bind(event.id, event.event_type, event.message, event.outage_id, event.source, event.created_at).run();
  }

  async updateOutage(outage: Outage): Promise<void> {
    const stmt = this.db.prepare(
      "UPDATE outages SET status = ?, confidence = ?, report_count = ?, first_signal_at = ?, started_at = ?, restored_at = ?, closed_at = ?, updated_at = ? WHERE id = ?"
    );
    await stmt.bind(outage.status, outage.confidence, outage.report_count, outage.first_signal_at, outage.started_at, outage.restored_at, outage.closed_at, utcNow(), outage.id).run();
  }

  async closeStaleOutages(): Promise<Outage[]> {
    const cutoff = new Date(Date.now() - CONFIG.staleSignalSeconds * 1000).toISOString();
    const stmt = this.db.prepare(
      `SELECT * FROM outages WHERE status IN (?, ?, ?, ?, ?) AND updated_at < ?`
    );
    const { results } = await stmt.bind(...ACTIVE_OUTAGE_STATUSES, cutoff).all();
    const stale = results as Outage[];
    const now = utcNow();
    for (const outage of stale) {
      if (outage.report_count < 2) {
        outage.status = "closed";
        outage.closed_at = now;
        const updateStmt = this.db.prepare("UPDATE outages SET status = ?, closed_at = ? WHERE id = ?");
        await updateStmt.bind(outage.status, outage.closed_at, outage.id).run();
        await this.logEvent("OUTAGE_CLOSED_STALE", outage);
      }
    }
    return stale;
  }

  async getActiveOutages(): Promise<Outage[]> {
    const stmt = this.db.prepare(
      `SELECT * FROM outages WHERE status IN (?, ?, ?, ?, ?) ORDER BY created_at DESC`
    );
    const { results } = await stmt.bind(...ACTIVE_OUTAGE_STATUSES).all();
    return results as Outage[];
  }

  async getOutageById(outageId: string): Promise<Outage | null> {
    const stmt = this.db.prepare("SELECT * FROM outages WHERE id = ?");
    const result = await stmt.bind(outageId).first();
    if (!result) return null;
    return result as Outage;
  }
}
