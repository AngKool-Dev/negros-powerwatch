export type OutageStatus = "possible" | "detected" | "community_confirmed" | "officially_confirmed" | "restoring" | "restored" | "closed" | "false_positive";

export type SignalType = "community_report" | "official_advisory" | "sensor" | "network" | "weather" | "scraper";

export type SourceType = "noreco_ii" | "ngcp" | "community" | "sensor" | "network" | "weather";

export type SourceStatus = "healthy" | "degraded" | "failed" | "unknown";

export interface GeographicArea {
  id: string;
  name: string;
  area_type: string;
  parent_id: string | null;
  latitude: number | null;
  longitude: number | null;
  metadata_json: string | null;
  created_at: string;
}

export interface Outage {
  id: string;
  status: OutageStatus;
  confidence: number;
  report_count: number;
  cause: string | null;
  notes: string | null;
  first_signal_at: string | null;
  detected_at: string | null;
  official_confirmed_at: string | null;
  started_at: string | null;
  estimated_restore_at: string | null;
  restored_at: string | null;
  closed_at: string | null;
  created_at: string;
  updated_at: string;
  areas: OutageArea[];
}

export interface OutageArea {
  id: string;
  outage_id: string;
  area_id: string;
  created_at: string;
}

export interface Signal {
  id: string;
  outage_id: string | null;
  source_id: string;
  signal_type: SignalType;
  timestamp: string;
  latitude: number | null;
  longitude: number | null;
  area_id: string | null;
  status: string;
  confidence: number;
  metadata_json: string | null;
  processed: boolean;
  created_at: string;
}

export interface CommunityReport {
  id: string;
  outage_id: string | null;
  session_id: string;
  timestamp: string;
  latitude: number | null;
  longitude: number | null;
  area_id: string | null;
  power_status: string;
  municipality: string | null;
  barangay: string | null;
  notes: string | null;
  device_info: string | null;
  ip_address: string | null;
  created_at: string;
}

export interface Source {
  id: string;
  name: string;
  source_type: SourceType;
  reliability: number;
  status: SourceStatus;
  last_seen: string | null;
  last_success: string | null;
  last_failure: string | null;
  latency_ms: number | null;
  metadata_json: string | null;
  created_at: string;
  updated_at: string;
}

export interface OfficialAdvisory {
  id: string;
  outage_id: string;
  source_id: string;
  advisory_type: string;
  title: string | null;
  content: string | null;
  url: string | null;
  published_at: string;
  created_at: string;
}

export interface PublicationEvent {
  id: string;
  outage_id: string;
  publisher_name: string;
  status: string;
  channel: string;
  content: string | null;
  external_id: string | null;
  url: string | null;
  attempt_count: number;
  last_error: string | null;
  published_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface SystemEvent {
  id: string;
  event_type: string;
  message: string;
  outage_id: string | null;
  source: string | null;
  metadata_json: string | null;
  created_at: string;
}

export interface SensorNode {
  id: string;
  name: string;
  area_id: string | null;
  latitude: number | null;
  longitude: number | null;
  last_heartbeat: string | null;
  last_power_status: string | null;
  firmware_version: string | null;
  is_active: boolean;
  metadata_json: string | null;
  created_at: string;
  updated_at: string;
}

export interface MapAreaStatus {
  area_id: string;
  area_name: string;
  status: string;
  confidence: number;
  outage_id: string | null;
  started_at: string | null;
  restored_at: string | null;
  report_count: number;
  center: [number, number] | null;
}
