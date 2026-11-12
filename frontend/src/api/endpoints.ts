import { apiRequest } from './client';
import type {
  AuthResponse,
  User,
  DashboardStats,
  ProductionOrder,
  ProductionEvent,
  Camera,
  DetectionImageResponse,
  ModelStatus,
  OdooStatus,
  OdooConfig,
  OdooConfigUpdate,
  OdooSyncResult,
  SystemSetting,
  YoloRuntimeConfiguration,
  YoloRuntimeStatus,
  YoloRuntimeMetrics,
  ProductionTrendPoint,
  RequestMetrics,
  AuditLog,
  ClassificationRule,
  ZoneRule,
  ZoneConfigResponse,
} from '../types';

// Auth
export async function loginApi(formData: FormData): Promise<AuthResponse> {
  return apiRequest<AuthResponse>('/auth/login', {
    method: 'POST',
    body: formData,
  });
}

export async function getMeApi(): Promise<User> {
  return apiRequest<User>('/auth/me');
}

export async function getUsersApi(skip = 0, limit = 100): Promise<User[]> {
  return apiRequest<User[]>(`/users?skip=${skip}&limit=${limit}`);
}

export async function createUserApi(user: {
  username: string;
  full_name: string;
  role: User['role'];
  allowed_zones: string[];
  is_active: boolean;
  password: string;
}): Promise<User> {
  return apiRequest<User>('/users', { method: 'POST', body: JSON.stringify(user) });
}

export async function updateUserApi(userId: number, user: {
  full_name?: string;
  role?: User['role'];
  allowed_zones?: string[];
  is_active?: boolean;
  password?: string;
}): Promise<User> {
  return apiRequest<User>(`/users/${userId}`, { method: 'PATCH', body: JSON.stringify(user) });
}

export async function deleteUserApi(userId: number): Promise<void> {
  return apiRequest<void>(`/users/${userId}`, { method: 'DELETE' });
}

export async function getAuditLogsApi(skip = 0, limit = 100): Promise<AuditLog[]> {
  return apiRequest<AuditLog[]>(`/audit?skip=${skip}&limit=${limit}`);
}

// Dashboard
export async function getDashboardStatsApi(): Promise<DashboardStats> {
  return apiRequest<DashboardStats>('/dashboard/stats');
}

export async function getRequestMetricsApi(): Promise<RequestMetrics> {
  return apiRequest<RequestMetrics>('/health/metrics');
}

export async function getDashboardProductionTrendsApi(
  start: string,
  end: string,
  intervalMinutes: number
): Promise<ProductionTrendPoint[]> {
  const params = new URLSearchParams({
    start,
    end,
    interval_minutes: intervalMinutes.toString(),
  });
  return apiRequest<ProductionTrendPoint[]>(`/dashboard/production-trends?${params.toString()}`);
}

// Vision & Model
export async function getModelStatusApi(): Promise<ModelStatus> {
  return apiRequest<ModelStatus>('/models/status');
}

export async function detectImageApi(
  file: File,
  cameraId?: number,
  confThreshold?: number,
  showConfidence = true
): Promise<DetectionImageResponse> {
  const formData = new FormData();
  formData.append('file', file);
  if (cameraId !== undefined) formData.append('camera_id', cameraId.toString());
  if (confThreshold !== undefined) formData.append('conf_threshold', confThreshold.toString());
  formData.append('show_confidence', showConfidence.toString());

  return apiRequest<DetectionImageResponse>('/detections/image', {
    method: 'POST',
    body: formData,
  });
}

export async function getDetectionsApi(skip = 0, limit = 50): Promise<any[]> {
  return apiRequest<any[]>(`/detections?skip=${skip}&limit=${limit}`);
}

// Production Orders
export async function getProductionOrdersApi(skip = 0, limit = 50, state?: string, stage?: string): Promise<ProductionOrder[]> {
  let query = `/production/orders?skip=${skip}&limit=${limit}`;
  if (state) query += `&state=${encodeURIComponent(state)}`;
  if (stage) query += `&stage=${encodeURIComponent(stage)}`;
  return apiRequest<ProductionOrder[]>(query);
}

export async function createProductionOrderApi(order: {
  name: string;
  product_name: string;
  zone: string;
  target_qty?: number;
  state?: string;
  notes?: string;
}): Promise<ProductionOrder> {
  return apiRequest<ProductionOrder>('/production/orders', {
    method: 'POST',
    body: JSON.stringify(order),
  });
}

export async function updateProductionOrderApi(orderId: number, order: {
  name?: string;
  product_name?: string;
  target_qty?: number;
  state?: string;
  current_stage?: string | null;
  zone?: string | null;
  produced_qty?: number;
  notes?: string | null;
}): Promise<ProductionOrder> {
  return apiRequest<ProductionOrder>(`/production/orders/${orderId}`, {
    method: 'PATCH',
    body: JSON.stringify(order),
  });
}

export async function deleteProductionOrderApi(orderId: number): Promise<void> {
  return apiRequest<void>(`/production/orders/${orderId}`, { method: 'DELETE' });
}

export async function getOrderTimelineApi(orderId: number): Promise<any> {
  return apiRequest<any>(`/production/orders/${orderId}/timeline`);
}

// Production Events
export async function getProductionEventsApi(params?: {
  skip?: number;
  limit?: number;
  stage?: string;
  camera_id?: number;
  order_id?: number;
  association_status?: string;
  sync_status?: string;
  date_from?: string;
  date_to?: string;
}): Promise<ProductionEvent[]> {
  const queryParams = createEventQueryParams(params);

  return apiRequest<ProductionEvent[]>(`/events?${queryParams.toString()}`);
}

function createEventQueryParams(params?: {
  skip?: number; limit?: number; stage?: string; camera_id?: number; order_id?: number;
  association_status?: string; sync_status?: string; date_from?: string; date_to?: string;
}): URLSearchParams {
  const queryParams = new URLSearchParams();
  Object.entries(params || {}).forEach(([key, value]) => {
    if (value !== undefined && value !== '') queryParams.set(key, String(value));
  });
  return queryParams;
}

async function downloadCsv(path: string): Promise<Blob> {
  const baseUrl = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1';
  const token = localStorage.getItem('cardinova_token');
  const headers = new Headers();
  if (token) headers.set('Authorization', `Bearer ${token}`);
  const response = await fetch(`${baseUrl}${path}`, { headers });
  if (!response.ok) throw new Error(`No se pudo exportar el archivo (${response.status})`);
  return response.blob();
}

export async function exportProductionOrdersCsvApi(state?: string, stage?: string): Promise<Blob> {
  const params = new URLSearchParams();
  if (state) params.set('state', state);
  if (stage) params.set('stage', stage);
  return downloadCsv(`/production/orders/export.csv?${params}`);
}

export async function exportDetectionsCsvApi(params?: {
  camera_id?: number; class_name?: string; date_from?: string; date_to?: string;
}): Promise<Blob> {
  const query = new URLSearchParams();
  Object.entries(params || {}).forEach(([key, value]) => {
    if (value !== undefined && value !== '') query.set(key, String(value));
  });
  return downloadCsv(`/detections/export.csv?${query}`);
}

export async function exportAuditCsvApi(): Promise<Blob> {
  return downloadCsv('/audit/export.csv');
}

export async function exportProductionEventsCsvApi(params?: {
  stage?: string; association_status?: string; sync_status?: string; date_from?: string; date_to?: string;
}): Promise<Blob> {
  return downloadCsv(`/events/export.csv?${createEventQueryParams(params)}`);
}

export async function associateEventApi(eventId: number, orderId: number): Promise<ProductionEvent> {
  return apiRequest<ProductionEvent>(`/events/${eventId}/associate`, {
    method: 'POST',
    body: JSON.stringify({ order_id: orderId }),
  });
}

export async function completeProductionUnitApi(eventId: number): Promise<ProductionEvent> {
  return apiRequest<ProductionEvent>(`/events/${eventId}/complete-unit`, { method: 'POST' });
}

export async function updateProductionEventApi(eventId: number, event: {
  stage?: string;
  confidence?: number;
  evidence_count?: number;
  event_timestamp?: string;
}): Promise<ProductionEvent> {
  return apiRequest<ProductionEvent>(`/events/${eventId}`, {
    method: 'PATCH',
    body: JSON.stringify(event),
  });
}

export async function deleteProductionEventApi(eventId: number): Promise<void> {
  return apiRequest<void>(`/events/${eventId}`, { method: 'DELETE' });
}

// Cameras
export async function getCamerasApi(): Promise<Camera[]> {
  return apiRequest<Camera[]>('/cameras');
}

export async function createCameraApi(data: {
  name: string;
  zone: string;
  source: string;
  confidence_threshold: number;
}): Promise<Camera> {
  return apiRequest<Camera>('/cameras', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function updateCameraApi(cameraId: number, data: Partial<Camera>): Promise<Camera> {
  return apiRequest<Camera>(`/cameras/${cameraId}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  });
}

export async function deleteCameraApi(cameraId: number): Promise<{ message: string }> {
  return apiRequest<{ message: string }>(`/cameras/${cameraId}`, {
    method: 'DELETE',
  });
}

export async function testCameraApi(cameraId: number): Promise<Camera> {
  return apiRequest<Camera>(`/cameras/${cameraId}/test`, {
    method: 'POST',
  });
}

export async function getCameraStreamTicketApi(cameraId: number): Promise<string> {
  const response = await apiRequest<{ ticket: string }>(`/cameras/${cameraId}/stream-ticket`, {
    method: 'POST',
  });
  return response.ticket;
}

export function getCameraStreamUrl(cameraId: number, ticket: string, showConfidence = true): string {
  const baseUrl = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1';
  return `${baseUrl}/cameras/${cameraId}/stream?ticket=${encodeURIComponent(ticket)}&show_confidence=${showConfidence}`;
}

// Odoo ERP
export async function getOdooConfigApi(): Promise<OdooConfig> {
  return apiRequest<OdooConfig>('/odoo/config');
}

export async function updateOdooConfigApi(config: OdooConfigUpdate): Promise<OdooConfig> {
  return apiRequest<OdooConfig>('/odoo/config', {
    method: 'PUT',
    body: JSON.stringify(config),
  });
}

export async function getOdooStatusApi(): Promise<OdooStatus> {
  return apiRequest<OdooStatus>('/odoo/status');
}

export async function syncOdooOrdersApi(): Promise<OdooSyncResult> {
  return apiRequest<OdooSyncResult>('/odoo/sync-orders', {
    method: 'POST',
  });
}

export async function syncOdooEventsApi(): Promise<any> {
  return apiRequest<any>('/odoo/sync-events', {
    method: 'POST',
  });
}

// System Settings
export async function getSettingsApi(): Promise<SystemSetting[]> {
  return apiRequest<SystemSetting[]>('/settings');
}

export async function updateSettingApi(key: string, value: string, description?: string): Promise<SystemSetting> {
  return apiRequest<SystemSetting>(`/settings/${key}`, {
    method: 'PUT',
    body: JSON.stringify({ value, description }),
  });
}

// Detection Zone Config
export async function getDetectionZonesApi(): Promise<ZoneConfigResponse> {
  return apiRequest<ZoneConfigResponse>('/detection-zones');
}

export async function updateDetectionZonesApi(
  zones: Record<string, ZoneRule>,
  classification_rules: ClassificationRule[],
): Promise<ZoneConfigResponse> {
  return apiRequest<ZoneConfigResponse>('/detection-zones', {
    method: 'PUT',
    body: JSON.stringify({ zones, classification_rules }),
  });
}

export async function resetDetectionZonesApi(): Promise<ZoneConfigResponse> {
  return apiRequest<ZoneConfigResponse>('/detection-zones/reset', { method: 'POST' });
}

export async function getYoloRuntimeConfigurationApi(): Promise<YoloRuntimeStatus> {
  return apiRequest<YoloRuntimeStatus>('/models/runtime');
}

export async function updateYoloRuntimeConfigurationApi(
  configuration: YoloRuntimeConfiguration
): Promise<YoloRuntimeStatus> {
  return apiRequest<YoloRuntimeStatus>('/models/runtime', {
    method: 'PUT',
    body: JSON.stringify(configuration),
  });
}

export async function getYoloRuntimeMetricsApi(): Promise<YoloRuntimeMetrics> {
  return apiRequest<YoloRuntimeMetrics>('/models/metrics');
}

// 2D Scale Map
