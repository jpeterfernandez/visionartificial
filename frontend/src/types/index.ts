export type UserRole = 'ADMIN' | 'OPERATOR' | 'VIEWER';

export interface User {
  id: number;
  username: string;
  full_name: string;
  role: UserRole;
  allowed_zones: string[];
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface AuditLog {
  id: number;
  actor_user_id?: number | null;
  actor_username: string;
  action: string;
  target_type: string;
  target_id?: string | null;
  details?: Record<string, unknown> | null;
  created_at: string;
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
  user: User;
}

export interface SystemStatusSummary {
  postgres_connected: boolean;
  yolo_loaded: boolean;
  odoo_connected: boolean;
  active_cameras_count: number;
  connected_cameras_count: number;
  api_latency_ms?: number;
}

export interface RequestMetrics {
  sample_count: number;
  error_count: number;
  error_rate_percent: number;
  average_latency_ms: number;
  p95_latency_ms: number;
  captured_at: string;
}

export interface StageCount {
  stage: string;
  count: number;
}

export interface ZoneMachineCount {
  zone: string;
  machine_count: number;
  stage_counts: Record<string, number>;
  classification_counts: Record<string, number>;
  vinyl_color_counts: Record<string, number>; // solo ALMACÉN: {naranja: 2, azul: 1, ...}
  last_updated?: string | null;
  warnings: string[];
}

export interface ProductionTrendPoint {
  timestamp: string;
  stage: string;
  count: number;
}

export interface Camera {
  id: number;
  name: string;
  zone: string;
  source: string;
  is_active: boolean;
  confidence_threshold: number;
  is_connected: boolean;
  last_detection_at?: string | null;
  last_check_at?: string | null;
  created_at: string;
  updated_at: string;
  // Conteo de objetos del snapshot periódico
  machine_count?: number | null;
  last_snapshot_at?: string | null;
  classification_counts?: Record<string, number> | null;
  vinyl_color_counts?: Record<string, number> | null; // solo ALMACÉN
}

export interface ProductionOrder {
  id: number;
  odoo_order_id?: number | null;
  name: string;
  product_name: string;
  state: string;
  current_stage?: string | null;
  zone: string | null;
  target_qty: number;
  produced_qty: number;
  notes?: string | null;
  last_sync_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface ProductionEvent {
  id: number;
  camera_id?: number | null;
  camera_name?: string | null;
  order_id?: number | null;
  order_name?: string | null;
  stage: string;
  event_type: string;
  association_status: 'PENDIENTE' | 'ASOCIADO' | 'RECHAZADO';
  sync_status: 'PENDIENTE' | 'SINCRONIZADO' | 'ERROR';
  confidence: number;
  evidence_count: number;
  origin: string;
  event_metadata?: Record<string, any> | null;
  event_timestamp: string;
  created_at: string;
}

export interface DashboardStats {
  status: SystemStatusSummary;
  total_orders: number;
  in_progress_orders: number;
  completed_orders: number;
  total_detections_today: number;
  total_events_today: number;
  pending_association_events_count: number;
  pending_sync_events_count: number;
  stage_distribution: StageCount[];
  zone_machine_counts: ZoneMachineCount[];
  recent_events: ProductionEvent[];
  cameras: Camera[];
}

export interface BoundingBox {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

export interface DetectionItem {
  class_id: number;
  class_name: string;
  stage_name?: string | null;
  confidence: number;
  bbox: BoundingBox;
}

export interface MachineClassification {
  stage: string | null;
  label: string;
  anchor_class: string;
  representative_class: string;
  classes: string[];
}

export interface DetectionImageResponse {
  model_status: string;
  inference_time_ms: number;
  total_detections: number;
  image_width: number;
  image_height: number;
  detections: DetectionItem[];
  classifications: MachineClassification[];
  annotated_image_base64?: string | null;
  saved_detections_count?: number;
  confirmed_event_id?: number | null;
}

export interface ModelStatus {
  loaded: boolean;
  model_path: string;
  device: string;
  classes: Record<string, string>;
  conf_threshold: number;
  iou_threshold: number;
  img_size: number;
}

export type YoloDeviceMode = 'auto' | 'cpu' | 'gpu';

export interface YoloRuntimeConfiguration {
  device_mode: YoloDeviceMode;
  cpu_threads: number;
  gpu_memory_fraction: number;
  img_size: number;
  stream_img_size: number;
  stream_interval_ms: number;
}

export interface YoloRuntimeStatus {
  enabled: boolean;
  environment: string;
  configuration?: YoloRuntimeConfiguration;
  active?: {
    device: string;
    device_reason: string;
    cpu_threads: number;
    gpu_memory_fraction: number;
    img_size: number;
    stream_img_size: number;
    stream_interval_ms: number;
  };
  hardware?: {
    cpu_logical_cores: number;
    cuda_available: boolean;
    cuda_version: string | null;
    gpus: Array<{
      index: number;
      name: string;
      total_memory_mb: number;
      free_memory_mb: number;
    }>;
    gpu_unavailable_reason: string | null;
  };
}

export interface YoloRuntimeMetrics {
  enabled: boolean;
  environment: string;
  captured_at?: string;
  process_cpu_percent?: number;
  process_memory_mb?: number;
  process_memory_percent?: number;
  system_memory_total_mb?: number;
  inference_last_ms?: number | null;
  inference_average_ms?: number | null;
  inference_samples?: number;
  gpu_memory_allocated_mb?: number | null;
  gpu_memory_reserved_mb?: number | null;
  gpu_memory_total_mb?: number | null;
}

export interface OdooStatus {
  enabled: boolean;
  configured: boolean;
  connected: boolean;
  base_url: string;
  database: string;
  username: string;
  server_version?: string | null;
  authenticated: boolean;
  error?: string | null;
}

export interface OdooConfig {
  enabled: boolean;
  base_url: string;
  database: string;
  username: string;
  api_key_configured: boolean;
  timeout: number;
}

export interface OdooConfigUpdate {
  base_url: string;
  database: string;
  username: string;
  timeout: number;
  api_key?: string;
  clear_api_key?: boolean;
}

export interface OdooSyncResult {
  synced_orders_count: number;
  new_orders: number;
  updated_orders: number;
  errors: string[];
}

export interface SystemSetting {
  key: string;
  value: string;
  description?: string | null;
  updated_at: string;
}


// --- Configuración de reglas de detección por zona ---

export interface ZoneRule {
  description: string;
  allowed: string[];
  blocked: string[];
}

export interface ClassificationRule {
  id: string;
  name: string;
  stage: 'DOBLADO' | 'ARMADO_ESTRUCTURAL' | 'VINILADO' | 'ALMACEN';
  anchor_class: string;
  required_classes: string[];
  one_of_classes: string[];
}

export interface ZoneConfigResponse {
  zones: Record<string, ZoneRule>;
  classification_rules: ClassificationRule[];
  available_classes: string[];
  updated_at?: string | null;
}
