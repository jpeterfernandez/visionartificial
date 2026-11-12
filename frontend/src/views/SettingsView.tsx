import React, { useState, useEffect, useCallback } from 'react';
import {
  getSettingsApi,
  updateSettingApi,
  getYoloRuntimeConfigurationApi,
  updateYoloRuntimeConfigurationApi,
  getYoloRuntimeMetricsApi,
  getDetectionZonesApi,
  updateDetectionZonesApi,
  resetDetectionZonesApi,
} from '../api/endpoints';
import type { ClassificationRule, SystemSetting, YoloRuntimeConfiguration, YoloRuntimeMetrics, YoloRuntimeStatus, ZoneConfigResponse, ZoneRule } from '../types';
import { Save, RefreshCw, ShieldAlert, Cpu, SlidersHorizontal, Link2, Activity, RotateCcw, Map, Plus, Trash2, ArrowUp, ArrowDown } from 'lucide-react';
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { useAuth } from '../context/useAuth';
import { showErrorToast, showSuccessToast } from '../utils/notifications';

const ODOO_SETTING_KEY = 'ODOO_INTEGRATION_ENABLED';

function isSettingEnabled(setting: SystemSetting | undefined): boolean {
  return ['true', '1', 'si', 'sí', 'enabled'].includes((setting?.value || '').trim().toLowerCase());
}

export const SettingsView: React.FC = () => {
  const { user } = useAuth();
  const [settingsList, setSettingsList] = useState<SystemSetting[]>([]);
  const [loading, setLoading] = useState(true);
  const [editingValues, setEditingValues] = useState<Record<string, string>>({});
  const [savingKey, setSavingKey] = useState<string | null>(null);
  const [runtimeStatus, setRuntimeStatus] = useState<YoloRuntimeStatus | null>(null);
  const [runtimeConfiguration, setRuntimeConfiguration] = useState<YoloRuntimeConfiguration | null>(null);
  const [savingRuntime, setSavingRuntime] = useState(false);
  const [runtimeMetrics, setRuntimeMetrics] = useState<YoloRuntimeMetrics[]>([]);
  const [metricsError, setMetricsError] = useState<string | null>(null);

  // Estado del panel de zonas
  const [zoneConfig, setZoneConfig] = useState<ZoneConfigResponse | null>(null);
  const [zoneEditing, setZoneEditing] = useState<Record<string, ZoneRule>>({});
  const [classificationRulesEditing, setClassificationRulesEditing] = useState<ClassificationRule[]>([]);
  const [savingZones, setSavingZones] = useState(false);
  const [zoneModalOpen, setZoneModalOpen] = useState<string | null>(null); // nombre de zona abierta

  const fetchSettings = useCallback(async () => {
    try {
      const [data, runtime, zones] = await Promise.all([
        getSettingsApi(),
        getYoloRuntimeConfigurationApi(),
        getDetectionZonesApi(),
      ]);
      setSettingsList(data);
      const map: Record<string, string> = {};
      data.forEach(s => { map[s.key] = s.value; });
      setEditingValues(map);
      setRuntimeStatus(runtime);
      setRuntimeConfiguration(runtime.configuration || null);
      setZoneConfig(zones);
      setZoneEditing(JSON.parse(JSON.stringify(zones.zones)));
      setClassificationRulesEditing(JSON.parse(JSON.stringify(zones.classification_rules || [])));
    } catch (err: any) {
      showErrorToast(err.message || 'Error cargando configuración del sistema');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (user?.role === 'ADMIN') {
      void Promise.resolve().then(fetchSettings);
    }
  }, [user?.role, fetchSettings]);

  useEffect(() => {
    if (!runtimeStatus?.enabled) return;

    let active = true;
    let fetching = false;
    const fetchMetrics = async () => {
      if (fetching) return;
      fetching = true;
      try {
        const metrics = await getYoloRuntimeMetricsApi();
        if (active && metrics.enabled) {
          setRuntimeMetrics(current => [...current, { ...metrics, captured_at: new Date().toISOString() }].slice(-60));
          setMetricsError(null);
        }
      } catch (error: any) {
        if (active) setMetricsError(error.message || 'No se pudieron consultar las métricas.');
      } finally {
        fetching = false;
      }
    };

    fetchMetrics();
    const interval = window.setInterval(fetchMetrics, 5000);
    return () => {
      active = false;
      window.clearInterval(interval);
    };
  }, [runtimeStatus?.enabled]);

  const handleSave = async (key: string) => {
    setSavingKey(key);
    try {
      await updateSettingApi(key, editingValues[key]);
      showSuccessToast(`Configuración '${key}' guardada exitosamente.`);
    } catch (err: any) {
      showErrorToast(err.message || 'Error guardando configuración');
    } finally {
      setSavingKey(null);
    }
  };

  const odooSetting = settingsList.find(setting => setting.key.toLowerCase() === ODOO_SETTING_KEY.toLowerCase());
  const odooEnabled = isSettingEnabled(odooSetting);

  const handleOdooToggle = async (enabled: boolean) => {
    setSavingKey(ODOO_SETTING_KEY);
    try {
      const updated = await updateSettingApi(
        odooSetting?.key || ODOO_SETTING_KEY,
        enabled ? 'true' : 'false',
        odooSetting?.description || 'Controla si el sistema utiliza la integración con Odoo.'
      );
      setSettingsList(current => [
        ...current.filter(setting => setting.key.toLowerCase() !== ODOO_SETTING_KEY.toLowerCase()),
        updated
      ]);
      showSuccessToast(`Integración con Odoo ${enabled ? 'activada' : 'desactivada'}.`);
    } catch (err: any) {
      showErrorToast(err.message || 'Error actualizando la integración con Odoo');
    } finally {
      setSavingKey(null);
    }
  };

  const handleRuntimeSave = async () => {
    if (!runtimeConfiguration) return;
    setSavingRuntime(true);
    try {
      const updated = await updateYoloRuntimeConfigurationApi(runtimeConfiguration);
      setRuntimeStatus(updated);
      setRuntimeConfiguration(updated.configuration || runtimeConfiguration);
      showSuccessToast(`YOLO aplicó la configuración en ${updated.active?.device || 'el dispositivo seleccionado'}.`);
    } catch (err: any) {
      showErrorToast(err.message || 'Error aplicando la configuración de YOLO');
    } finally {
      setSavingRuntime(false);
    }
  };

  const handleRuntimeReset = async () => {
    const defaultThreads = Math.min(runtimeStatus?.hardware?.cpu_logical_cores || 2, 2);
    const defaults: YoloRuntimeConfiguration = {
      device_mode: 'auto',
      cpu_threads: defaultThreads,
      gpu_memory_fraction: 0.8,
      img_size: 416,
      stream_img_size: 224,
      stream_interval_ms: 200
    };
    setSavingRuntime(true);
    try {
      const updated = await updateYoloRuntimeConfigurationApi(defaults);
      setRuntimeStatus(updated);
      setRuntimeConfiguration(updated.configuration || defaults);
      showSuccessToast('Recursos de YOLO restablecidos a los valores predeterminados óptimos.');
    } catch (err: any) {
      showErrorToast(err.message || 'Error restableciendo la configuración predeterminada');
    } finally {
      setSavingRuntime(false);
    }
  };

  // --- Handlers de zonas ---
  const handleZoneClassToggle = (
    zoneName: string,
    cls: string,
    field: 'allowed' | 'blocked',
    checked: boolean
  ) => {
    setZoneEditing(prev => {
      const zone = { ...prev[zoneName], [field]: [...(prev[zoneName]?.[field] ?? [])] };
      if (checked) {
        if (!zone[field].includes(cls)) zone[field] = [...zone[field], cls];
        // mutuamente excluyentes: si está en blocked, quitar; si está en allowed, quitar del otro
        const other = field === 'allowed' ? 'blocked' : 'allowed';
        zone[other] = (zone[other] ?? []).filter(c => c !== cls);
      } else {
        zone[field] = zone[field].filter(c => c !== cls);
      }
      return { ...prev, [zoneName]: zone };
    });
  };

  const handleZoneSave = async () => {
    setSavingZones(true);
    try {
      const updated = await updateDetectionZonesApi(zoneEditing, classificationRulesEditing);
      setZoneConfig(updated);
      setZoneEditing(JSON.parse(JSON.stringify(updated.zones)));
      setClassificationRulesEditing(JSON.parse(JSON.stringify(updated.classification_rules)));
      showSuccessToast('Reglas de detección por zona guardadas correctamente.');
    } catch (err: any) {
      showErrorToast(err.message || 'Error guardando reglas de zona');
    } finally {
      setSavingZones(false);
    }
  };

  const handleZoneReset = async () => {
    setSavingZones(true);
    try {
      const updated = await resetDetectionZonesApi();
      setZoneConfig(updated);
      setZoneEditing(JSON.parse(JSON.stringify(updated.zones)));
      setClassificationRulesEditing(JSON.parse(JSON.stringify(updated.classification_rules)));
      showSuccessToast('Reglas de zona restablecidas a los valores por defecto.');
    } catch (err: any) {
      showErrorToast(err.message || 'Error restableciendo reglas de zona');
    } finally {
      setSavingZones(false);
    }
  };

  const updateClassificationRule = (ruleId: string, updates: Partial<ClassificationRule>) => {
    setClassificationRulesEditing(previous => previous.map(rule =>
      rule.id === ruleId ? { ...rule, ...updates } : rule
    ));
  };

  const moveClassificationRule = (index: number, offset: -1 | 1) => {
    setClassificationRulesEditing(previous => {
      const target = index + offset;
      if (target < 0 || target >= previous.length) return previous;
      const reordered = [...previous];
      [reordered[index], reordered[target]] = [reordered[target], reordered[index]];
      return reordered;
    });
  };

  const addClassificationRule = () => {
    const firstClass = zoneConfig?.available_classes[0] || 'chasis_base';
    setClassificationRulesEditing(previous => [...previous, {
      id: `regla-${Date.now()}`,
      name: 'Nueva clasificación',
      stage: 'DOBLADO',
      anchor_class: firstClass,
      required_classes: [],
      one_of_classes: [],
    }]);
  };


  if (user?.role !== 'ADMIN') {
    return (
      <div className="view-container settings-view">
        <div className="settings-restricted">
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <ShieldAlert size={24} style={{ color: '#d97706' }} />
            <div>
              <h3 style={{ fontWeight: 600 }}>Acceso Restringido</h3>
              <p style={{ color: '#64748b', fontSize: '0.85rem' }}>
                Solo los usuarios con rol <strong>ADMIN</strong> tienen autorización para modificar los parámetros globales del sistema.
              </p>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="view-container settings-view">
      <header className="settings-hero">
        <div className="settings-hero-copy">
          <span className="settings-eyebrow"><SlidersHorizontal size={14} /> Administración</span>
          <h1>Configuración del sistema</h1>
          <p>Gestiona integraciones, parámetros de inferencia y detalles de la plataforma.</p>
        </div>
        <button onClick={() => { setLoading(true); void fetchSettings(); }} disabled={loading} className="settings-refresh">
          <RefreshCw size={15} className={loading ? 'animate-spin' : undefined} />
          Recargar ajustes
        </button>
      </header>

      <div className="settings-content">
        <section className="settings-section" aria-labelledby="settings-integrations-title">
          <div className="settings-section-heading">
            <span className="settings-icon"><Link2 size={18} /></span>
            <div>
              <span className="settings-kicker">Conexiones</span>
              <h2 id="settings-integrations-title">Integraciones</h2>
            </div>
          </div>
          <div className="settings-integration-row">
            <div className="settings-row-copy">
              <strong>Odoo ERP</strong>
              <span>Permite sincronizar órdenes y eventos con la plataforma ERP.</span>
            </div>
            <div className="settings-integration-control">
              <span className={`settings-status ${odooEnabled ? 'is-enabled' : ''}`}>
                <span />{odooEnabled ? 'Activa' : 'Inactiva'}
              </span>
              <label className="settings-switch-label">
                <span className="settings-visually-hidden">Permitir integración con Odoo ERP</span>
                <input
                  className="settings-switch"
                  type="checkbox"
                  checked={odooEnabled}
                  disabled={loading || savingKey === ODOO_SETTING_KEY}
                  onChange={event => handleOdooToggle(event.target.checked)}
                  aria-label="Permitir integración con Odoo ERP"
                />
              </label>
            </div>
          </div>
        </section>

        <section className="settings-section" aria-labelledby="settings-parameters-title">
          <div className="settings-section-heading">
            <span className="settings-icon"><Cpu size={18} /></span>
            <div>
              <span className="settings-kicker">Plataforma</span>
              <h2 id="settings-parameters-title">Parámetros del sistema</h2>
            </div>
          </div>
          {settingsList.filter(st => !st.key.toUpperCase().startsWith('ODOO_')).length === 0 && !loading ? (
            <div className="settings-empty">No hay parámetros configurables disponibles.</div>
          ) : (
            <div className="settings-parameter-list">
              {settingsList.filter(st => !st.key.toUpperCase().startsWith('ODOO_')).map(st => (
                <article key={st.key} className="settings-parameter">
                  <div className="settings-parameter-heading">
                    <div className="settings-row-copy">
                      <h3>{st.key}</h3>
                      <span>{st.description || 'Sin descripción'}</span>
                    </div>
                    <time dateTime={st.updated_at} className="settings-updated">
                      Actualizado {new Date(st.updated_at).toLocaleString()}
                    </time>
                  </div>
                  <div className="settings-editor">
                    <textarea
                      className="input-control settings-textarea"
                      rows={3}
                      aria-label={`Valor para ${st.key}`}
                      value={editingValues[st.key] || ''}
                      onChange={event => setEditingValues({ ...editingValues, [st.key]: event.target.value })}
                    />
                    <button
                      onClick={() => handleSave(st.key)}
                      disabled={savingKey === st.key}
                      className="btn settings-save"
                    >
                      {savingKey === st.key ? <RefreshCw className="animate-spin" size={16} /> : <Save size={16} />}
                      Guardar
                    </button>
                  </div>
                </article>
              ))}
            </div>
          )}
        </section>

        {runtimeStatus?.enabled && runtimeStatus.hardware && runtimeConfiguration && (
          <section className="settings-section" aria-labelledby="settings-yolo-runtime-title">
            <div className="settings-section-heading">
              <span className="settings-icon"><Cpu size={18} /></span>
              <div>
                <span className="settings-kicker">Solo desarrollo</span>
                <h2 id="settings-yolo-runtime-title">Recursos de visión artificial</h2>
              </div>
            </div>
            <div className="settings-runtime-content">
              <div className="settings-metrics-heading">
                <div>
                  <strong>Consumo y rendimiento del backend</strong>
                  <span>Actualización cada 5 segundos · últimas 5 minutos</span>
                </div>
                <Activity size={18} aria-hidden="true" />
              </div>
              {runtimeMetrics.length > 0 && (() => {
                const latest = runtimeMetrics[runtimeMetrics.length - 1];
                const chartData = runtimeMetrics.map((sample, index) => ({
                  ...sample,
                  sample: index,
                  time: sample.captured_at ? new Date(sample.captured_at).toLocaleTimeString() : '',
                  gpu_memory_percent: sample.gpu_memory_allocated_mb != null && sample.gpu_memory_total_mb
                    ? sample.gpu_memory_allocated_mb / sample.gpu_memory_total_mb * 100
                    : null,
                }));
                return (
                  <>
                    <div className="settings-metrics-summary">
                      <div><span>CPU del proceso</span><strong>{latest.process_cpu_percent?.toFixed(1) ?? '--'}%</strong></div>
                      <div><span>RAM del proceso</span><strong>{latest.process_memory_mb?.toFixed(0) ?? '--'} MB</strong></div>
                      <div><span>VRAM YOLO</span><strong>
                        {latest.gpu_memory_allocated_mb == null ? 'No disponible' : `${latest.gpu_memory_allocated_mb.toFixed(0)} / ${latest.gpu_memory_total_mb?.toFixed(0) ?? '--'} MB`}
                      </strong></div>
                      <div><span>Inferencia promedio</span><strong>{latest.inference_average_ms == null ? '--' : `${latest.inference_average_ms.toFixed(1)} ms`}</strong></div>
                    </div>
                    <div className="settings-metrics-chart" role="img" aria-label="Gráfico de CPU, RAM y VRAM del backend durante los últimos cinco minutos">
                      <ResponsiveContainer width="100%" height="100%">
                        <LineChart data={chartData} margin={{ top: 8, right: 14, left: -18, bottom: 0 }}>
                          <CartesianGrid stroke="#e5e9ec" strokeDasharray="3 5" vertical={false} />
                          <XAxis dataKey="sample" tickFormatter={(_, index) => chartData[index]?.time || ''} tick={{ fill: '#64748b', fontSize: 10 }} tickLine={false} axisLine={false} minTickGap={24} />
                          <YAxis domain={[0, 100]} unit="%" tick={{ fill: '#64748b', fontSize: 10 }} tickLine={false} axisLine={false} />
                          <Tooltip labelFormatter={(_, payload) => payload?.[0]?.payload?.time || ''} formatter={(value, name) => [`${Number(value).toFixed(1)}%`, name]} />
                          <Legend wrapperStyle={{ fontSize: 11 }} />
                          <Line type="monotone" dataKey="process_cpu_percent" name="CPU backend" stroke="#087e91" strokeWidth={2} dot={false} isAnimationActive={false} />
                          <Line type="monotone" dataKey="process_memory_percent" name="RAM backend" stroke="#d97706" strokeWidth={2} dot={false} isAnimationActive={false} />
                          {latest.gpu_memory_allocated_mb != null && <Line type="monotone" dataKey="gpu_memory_percent" name="VRAM YOLO" stroke="#16a34a" strokeWidth={2} dot={false} isAnimationActive={false} />}
                        </LineChart>
                      </ResponsiveContainer>
                    </div>
                    <div className="settings-metrics-footnote">
                      {latest.inference_samples
                        ? `Latencia de inferencia: última ${latest.inference_last_ms?.toFixed(1) ?? '--'} ms · promedio de ${latest.inference_samples} inferencias recientes.`
                        : 'Aún no hay inferencias registradas desde que inició el backend.'}
                      {metricsError && <span role="status"> {metricsError}</span>}
                    </div>
                  </>
                );
              })()}
              {runtimeMetrics.length === 0 && (
                <div className="settings-metrics-empty" role="status">
                  {metricsError || 'Esperando la primera lectura de recursos del backend...'}
                </div>
              )}
              <div className="settings-runtime-warning" role="note">
                <ShieldAlert size={19} />
                <div>
                  <strong>Configuración experimental</strong>
                  <span>Cambiar CPU/GPU o el límite de memoria GPU puede recargar YOLO; los hilos y las resoluciones se aplican sin recargar el modelo. En producción este control y su API están deshabilitados.</span>
                </div>
              </div>

              <div className="settings-runtime-grid">
                <label className="settings-runtime-field">
                  <span>Procesador</span>
                  <select
                    className="input-control"
                    value={runtimeConfiguration.device_mode}
                    onChange={event => setRuntimeConfiguration({
                      ...runtimeConfiguration,
                      device_mode: event.target.value as YoloRuntimeConfiguration['device_mode']
                    })}
                    disabled={savingRuntime}
                  >
                    <option value="auto">Automático</option>
                    <option value="cpu">CPU</option>
                    <option value="gpu" disabled={!runtimeStatus.hardware.cuda_available}>GPU CUDA</option>
                  </select>
                  <small>Automático usa CUDA solo si PyTorch detecta una GPU NVIDIA compatible; la Intel Iris Xe se procesa por CPU.</small>
                </label>

                <label className="settings-runtime-field">
                  <span>Hilos CPU</span>
                  <input
                    className="input-control"
                    type="number"
                    min={1}
                    max={Math.min(runtimeStatus.hardware.cpu_logical_cores, 2)}
                    value={runtimeConfiguration.cpu_threads}
                    onChange={event => setRuntimeConfiguration({
                      ...runtimeConfiguration,
                      cpu_threads: Number(event.target.value)
                    })}
                    disabled={savingRuntime}
                  />
                  <small>{runtimeStatus.hardware.cpu_logical_cores} núcleos lógicos detectados.</small>
                </label>

                {(runtimeConfiguration.device_mode === 'gpu' || (runtimeConfiguration.device_mode === 'auto' && runtimeStatus.hardware.cuda_available)) && (
                  <label className="settings-runtime-field">
                    <span>Límite de memoria GPU</span>
                    <div className="settings-runtime-range">
                      <input
                        type="range"
                        min={50}
                        max={100}
                        step={5}
                        value={Math.round(runtimeConfiguration.gpu_memory_fraction * 100)}
                        onChange={event => setRuntimeConfiguration({
                          ...runtimeConfiguration,
                          gpu_memory_fraction: Number(event.target.value) / 100
                        })}
                        disabled={savingRuntime}
                      />
                      <output>{Math.round(runtimeConfiguration.gpu_memory_fraction * 100)}%</output>
                    </div>
                    <small>Tope de memoria CUDA para este proceso.</small>
                  </label>
                )}

                <label className="settings-runtime-field">
                  <span>Resolución de inferencia</span>
                  <select
                    className="input-control"
                    value={runtimeConfiguration.img_size}
                    onChange={event => setRuntimeConfiguration({
                      ...runtimeConfiguration,
                      img_size: Number(event.target.value)
                    })}
                    disabled={savingRuntime}
                  >
                    {[320, 416, 512, 640, 768].map(size => <option key={size} value={size}>{size}px</option>)}
                  </select>
                  <small>Se usa para imágenes y capturas periódicas. 320 px consume menos recursos; 416 px equilibra velocidad y detalle.</small>
                </label>

                <label className="settings-runtime-field">
                  <span>Resolución del stream</span>
                  <select
                    className="input-control"
                    value={runtimeConfiguration.stream_img_size}
                    onChange={event => setRuntimeConfiguration({
                      ...runtimeConfiguration,
                      stream_img_size: Number(event.target.value)
                    })}
                    disabled={savingRuntime}
                  >
                    {[224, 256, 320, 416, 512, 640].map(size => <option key={size} value={size}>{size}px</option>)}
                  </select>
                  <small>224 px reduce la carga en equipos lentos; sube la resolución si necesitas detectar objetos pequeños.</small>
                </label>

                <label className="settings-runtime-field">
                  <span>Velocidad máxima del stream</span>
                  <select
                    className="input-control"
                    value={runtimeConfiguration.stream_interval_ms}
                    onChange={event => setRuntimeConfiguration({
                      ...runtimeConfiguration,
                      stream_interval_ms: Number(event.target.value)
                    })}
                    disabled={savingRuntime}
                  >
                    {[100, 120, 200, 333, 500, 1000].map(interval => (
                      <option key={interval} value={interval}>
                        {`${Math.round(1000 / interval)} FPS`}
                      </option>
                    ))}
                  </select>
                  <small>Máximo 10 FPS; predeterminado 5 FPS. Bájalo a 1 FPS si la PC se ralentiza. La inferencia también queda limitada a esa velocidad.</small>
                </label>
              </div>

              <div className="settings-runtime-hardware">
                <strong>Hardware detectado</strong>
                <span>CPU: {runtimeStatus.hardware.cpu_logical_cores} núcleos lógicos</span>
                {runtimeStatus.hardware.cuda_available
                  ? runtimeStatus.hardware.gpus.map(gpu => (
                    <span key={gpu.index}>GPU {gpu.index}: {gpu.name} · {gpu.free_memory_mb} MB libres de {gpu.total_memory_mb} MB</span>
                  ))
                  : <span>{runtimeStatus.hardware.gpu_unavailable_reason || 'No hay GPU CUDA compatible.'}</span>}
              </div>

              <div className="settings-runtime-footer">
                <span>Activo: {runtimeStatus.active?.device.toUpperCase() || 'desconocido'} · {runtimeStatus.active?.device_reason}</span>
                <div style={{ display: 'flex', gap: '8px' }}>
                  <button
                    type="button"
                    onClick={handleRuntimeReset}
                    disabled={savingRuntime}
                    className="btn btn-outline"
                    title="Restablecer configuración predeterminada optimizada para CPU"
                  >
                    <RotateCcw size={15} />
                    Restablecer
                  </button>
                  <button
                    type="button"
                    onClick={handleRuntimeSave}
                    disabled={savingRuntime || !runtimeConfiguration.cpu_threads}
                    className="btn settings-save"
                  >
                    {savingRuntime ? <RefreshCw className="animate-spin" size={16} /> : <Save size={16} />}
                    Aplicar recursos
                  </button>
                </div>
              </div>
            </div>
          </section>
        )}

        {/* ── Reglas de detección por zona — botón que abre el modal ─── */}
        {zoneConfig && (
          <section className="settings-section" aria-labelledby="settings-zones-title">
            <div className="settings-section-heading">
              <span className="settings-icon"><Map size={18} /></span>
              <div>
                <span className="settings-kicker">Visión artificial</span>
                <h2 id="settings-zones-title">Reglas de detección por zona</h2>
              </div>
            </div>
            <p style={{ fontSize: '0.82rem', color: '#64748b', margin: '0 0 16px' }}>
              Configura qué clases detecta YOLO en cada zona de producción.
              {zoneConfig.updated_at && (
                <span style={{ color: '#94a3b8', marginLeft: '8px' }}>
                  Última actualización: {new Date(zoneConfig.updated_at).toLocaleString()}
                </span>
              )}
            </p>
            {/* Resumen de zonas como tarjetas de entrada al modal */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: '10px', marginBottom: '16px' }}>
              {Object.entries(zoneEditing).map(([zoneName, rule]) => {
                const ZONE_COLORS: Record<string, string> = {
                  DOBLADO: '#3b82f6', ARMADO_ESTRUCTURAL: '#f59e0b',
                  VINILADO: '#8b5cf6', ALMACEN: '#10b981',
                };
                const color = ZONE_COLORS[zoneName] ?? '#64748b';
                return (
                  <button
                    key={zoneName}
                    type="button"
                    onClick={() => setZoneModalOpen(zoneName)}
                    style={{
                      display: 'flex', flexDirection: 'column', alignItems: 'flex-start',
                      gap: '4px', padding: '12px 14px',
                      border: `1px solid ${color}33`,
                      borderLeft: `4px solid ${color}`,
                      borderRadius: '8px', background: '#fff',
                      cursor: 'pointer', textAlign: 'left',
                      transition: 'box-shadow 0.15s',
                    }}
                    onMouseEnter={e => (e.currentTarget.style.boxShadow = `0 4px 14px ${color}22`)}
                    onMouseLeave={e => (e.currentTarget.style.boxShadow = 'none')}
                  >
                    <span style={{ fontWeight: 700, fontSize: '0.84rem', color: '#0f172a' }}>{zoneName}</span>
                    <span style={{ fontSize: '0.70rem', color: '#64748b' }}>
                      {rule.allowed.length > 0
                        ? `${rule.allowed.length} clase${rule.allowed.length !== 1 ? 's' : ''} permitida${rule.allowed.length !== 1 ? 's' : ''}`
                        : 'Todas las clases'}
                      {rule.blocked.length > 0 && ` · ${rule.blocked.length} bloqueada${rule.blocked.length !== 1 ? 's' : ''}`}
                    </span>
                    <span style={{ fontSize: '0.66rem', color, fontWeight: 600, marginTop: '2px' }}>
                      Configurar →
                    </span>
                  </button>
                );
              })}
            </div>
            <div style={{ borderTop: '1px solid #e2e8f0', paddingTop: '16px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '12px', marginBottom: '8px' }}>
                <h3 style={{ margin: 0, color: '#0f172a', fontSize: '0.95rem' }}>Clasificación dinámica de máquinas</h3>
                <div style={{ display: 'flex', gap: '8px' }}>
                  <button type="button" className="btn btn-outline btn-sm" onClick={addClassificationRule} disabled={savingZones}>
                    <Plus size={14} /> Agregar regla
                  </button>
                  <button type="button" className="btn settings-save btn-sm" onClick={() => void handleZoneSave()} disabled={savingZones}>
                    {savingZones ? <RefreshCw className="animate-spin" size={14} /> : <Save size={14} />}
                    Guardar reglas
                  </button>
                </div>
              </div>
              <p style={{ fontSize: '0.78rem', lineHeight: 1.5, color: '#64748b', margin: '0 0 12px' }}>
                Agrupa las clases que caen dentro de cada chasis. Las clases requeridas deben estar todas presentes;
                basta una de las alternativas. Si coinciden varias reglas, se aplica primero la que aparece arriba.
                Los cambios también se reflejan en eventos y conteos de cámara.
              </p>
              {classificationRulesEditing.length === 0 && (
                <p style={{ color: '#64748b', fontSize: '0.82rem' }}>No hay reglas configuradas; se usará el mapeo de etapas existente.</p>
              )}
              <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                {classificationRulesEditing.map((classificationRule, index) => {
                  const inputStyle: React.CSSProperties = {
                    width: '100%', boxSizing: 'border-box', minHeight: '36px',
                    border: '1px solid #cbd5e1', borderRadius: '6px', padding: '7px 9px',
                    color: '#0f172a', background: '#fff', fontSize: '0.8rem',
                  };
                  return (
                    <div key={classificationRule.id} style={{ border: '1px solid #e2e8f0', borderRadius: '8px', padding: '12px', background: '#f8fafc' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
                        <strong style={{ color: '#334155', fontSize: '0.8rem' }}>Regla {index + 1}</strong>
                        <div style={{ display: 'flex', gap: '4px' }}>
                          <button type="button" className="btn btn-outline btn-sm" aria-label="Subir prioridad" title="Subir prioridad" disabled={index === 0 || savingZones} onClick={() => moveClassificationRule(index, -1)}><ArrowUp size={14} /></button>
                          <button type="button" className="btn btn-outline btn-sm" aria-label="Bajar prioridad" title="Bajar prioridad" disabled={index === classificationRulesEditing.length - 1 || savingZones} onClick={() => moveClassificationRule(index, 1)}><ArrowDown size={14} /></button>
                          <button type="button" className="btn btn-outline btn-sm" aria-label="Eliminar regla" title="Eliminar regla" disabled={savingZones} onClick={() => setClassificationRulesEditing(previous => previous.filter(rule => rule.id !== classificationRule.id))}><Trash2 size={14} /></button>
                        </div>
                      </div>
                      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))', gap: '10px' }}>
                        <label style={{ fontSize: '0.74rem', color: '#475569' }}>
                          Nombre visible
                          <input style={inputStyle} value={classificationRule.name} maxLength={100} onChange={event => updateClassificationRule(classificationRule.id, { name: event.target.value })} />
                        </label>
                        <label style={{ fontSize: '0.74rem', color: '#475569' }}>
                          Etapa del proceso
                          <select style={inputStyle} value={classificationRule.stage} onChange={event => updateClassificationRule(classificationRule.id, { stage: event.target.value as ClassificationRule['stage'] })}>
                            <option value="DOBLADO">Doblado</option>
                            <option value="ARMADO_ESTRUCTURAL">Armado estructural</option>
                            <option value="VINILADO">Vinilado</option>
                            <option value="ALMACEN">Almacén</option>
                          </select>
                        </label>
                        <label style={{ fontSize: '0.74rem', color: '#475569' }}>
                          Clase principal (ancla)
                          <input style={inputStyle} value={classificationRule.anchor_class} onChange={event => updateClassificationRule(classificationRule.id, { anchor_class: event.target.value.trim() })} placeholder="chasis_base" />
                        </label>
                        <label style={{ fontSize: '0.74rem', color: '#475569' }}>
                          Requiere todas estas clases
                          <input
                            style={inputStyle}
                            value={classificationRule.required_classes.join(', ')}
                            onChange={event => updateClassificationRule(classificationRule.id, { required_classes: event.target.value.split(',').map(value => value.trim()).filter(Boolean) })}
                            placeholder="cavidad_hueca"
                          />
                        </label>
                        <label style={{ fontSize: '0.74rem', color: '#475569', gridColumn: '1 / -1' }}>
                          O requiere al menos una de estas clases
                          <input
                            style={inputStyle}
                            value={classificationRule.one_of_classes.join(', ')}
                            onChange={event => updateClassificationRule(classificationRule.id, { one_of_classes: event.target.value.split(',').map(value => value.trim()).filter(Boolean) })}
                            placeholder="puerta_inferior, puerta_sup_chapa, puerta_sup_panel"
                          />
                        </label>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </section>
        )}

        {/* ── Modal flotante de configuración de zona ───────────────────── */}
        {zoneModalOpen && zoneConfig && (() => {
          const zoneName = zoneModalOpen;
          const rule = zoneEditing[zoneName] ?? { description: '', allowed: [], blocked: [] };
          const ZONE_COLORS: Record<string, string> = {
            DOBLADO: '#3b82f6', ARMADO_ESTRUCTURAL: '#f59e0b',
            VINILADO: '#8b5cf6', ALMACEN: '#10b981',
          };
          const color = ZONE_COLORS[zoneName] ?? '#64748b';
          return (
            <div
              role="dialog"
              aria-modal="true"
              aria-labelledby="zone-modal-title"
              style={{
                position: 'fixed', inset: 0, zIndex: 10000,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                backgroundColor: 'rgba(15,23,42,0.55)',
                backdropFilter: 'blur(3px)',
                padding: '16px',
              }}
              onClick={e => { if (e.target === e.currentTarget) setZoneModalOpen(null); }}
            >
              <div style={{
                background: '#fff', borderRadius: '14px',
                boxShadow: '0 24px 64px rgba(0,0,0,0.22)',
                width: '100%', maxWidth: '560px',
                maxHeight: '90vh', display: 'flex', flexDirection: 'column',
                overflow: 'hidden',
              }}>
                {/* Cabecera */}
                <div style={{
                  padding: '18px 22px 14px',
                  borderBottom: '1px solid #f1f5f9',
                  borderTop: `4px solid ${color}`,
                  display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '12px',
                }}>
                  <div>
                    <h2 id="zone-modal-title" style={{ fontSize: '1rem', fontWeight: 700, color: '#0f172a', margin: 0 }}>
                      {zoneName}
                    </h2>
                    {rule.description && (
                      <p style={{ fontSize: '0.76rem', color: '#64748b', margin: '4px 0 0' }}>{rule.description}</p>
                    )}
                  </div>
                  <button
                    type="button" onClick={() => setZoneModalOpen(null)}
                    aria-label="Cerrar"
                    style={{
                      background: 'none', border: 'none', cursor: 'pointer',
                      color: '#94a3b8', padding: '2px', fontSize: '1.2rem', lineHeight: 1,
                    }}
                  >✕</button>
                </div>

                {/* Cuerpo scrollable */}
                <div style={{ padding: '18px 22px', overflowY: 'auto', flex: 1 }}>
                  {zoneConfig.available_classes.length === 0 && (
                    <p style={{ color: '#d97706', fontSize: '0.82rem', marginBottom: '12px' }}>
                      El modelo YOLO no está cargado aún.
                    </p>
                  )}
                  <p style={{ fontSize: '0.78rem', color: '#64748b', marginBottom: '16px', lineHeight: 1.5 }}>
                    <strong>Permitidas:</strong> solo esas clases se cuentan.
                    Si no marcás ninguna, se permiten todas.
                    <br />
                    <strong>Bloqueadas:</strong> esas clases se ignoran siempre, aunque estén en la lista de permitidas.
                  </p>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px' }}>
                    {(['allowed', 'blocked'] as const).map(field => (
                      <div key={field}>
                        <p style={{
                          fontSize: '0.72rem', fontWeight: 700, textTransform: 'uppercase',
                          color: field === 'allowed' ? '#059669' : '#dc2626',
                          marginBottom: '10px', display: 'flex', alignItems: 'center', gap: '5px',
                        }}>
                          {field === 'allowed' ? '✓ Solo permitir' : '✗ Bloquear siempre'}
                        </p>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                          {zoneConfig.available_classes.map(cls => {
                            const checked = (rule[field] ?? []).includes(cls);
                            const disabledByOther = field === 'allowed'
                              ? (rule.blocked ?? []).includes(cls)
                              : (rule.allowed ?? []).includes(cls);
                            return (
                              <label key={cls} style={{
                                display: 'flex', alignItems: 'center', gap: '8px',
                                fontSize: '0.80rem',
                                cursor: disabledByOther ? 'not-allowed' : 'pointer',
                                color: disabledByOther ? '#cbd5e1' : '#0f172a',
                                padding: '5px 8px', borderRadius: '6px',
                                background: checked ? (field === 'allowed' ? '#f0fdf4' : '#fff1f2') : 'transparent',
                                border: `1px solid ${checked ? (field === 'allowed' ? '#bbf7d0' : '#fecaca') : '#e2e8f0'}`,
                                transition: 'background 0.12s',
                              }}>
                                <input
                                  type="checkbox"
                                  checked={checked}
                                  disabled={disabledByOther || savingZones}
                                  onChange={e => handleZoneClassToggle(zoneName, cls, field, e.target.checked)}
                                  style={{ accentColor: field === 'allowed' ? '#059669' : '#dc2626' }}
                                />
                                <span>{cls.replace('chasis_', '')}</span>
                              </label>
                            );
                          })}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Footer */}
                <div style={{
                  padding: '14px 22px',
                  borderTop: '1px solid #f1f5f9',
                  display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '10px',
                  background: '#fafafa',
                }}>
                  <button
                    type="button" onClick={handleZoneReset} disabled={savingZones}
                    className="btn btn-outline btn-sm"
                    style={{ fontSize: '0.76rem' }}
                  >
                    <RotateCcw size={13} /> Restablecer todos los defaults
                  </button>
                  <div style={{ display: 'flex', gap: '8px' }}>
                    <button
                      type="button" onClick={() => setZoneModalOpen(null)}
                      className="btn btn-outline btn-sm"
                      style={{ fontSize: '0.76rem' }}
                    >
                      Cancelar
                    </button>
                    <button
                      type="button" onClick={() => { void handleZoneSave().then(() => setZoneModalOpen(null)); }}
                      disabled={savingZones} className="btn settings-save btn-sm"
                      style={{ fontSize: '0.76rem' }}
                    >
                      {savingZones ? <RefreshCw className="animate-spin" size={13} /> : <Save size={13} />}
                      Guardar y cerrar
                    </button>
                  </div>
                </div>
              </div>
            </div>
          );
        })()}

        <section className="settings-environment" aria-labelledby="settings-environment-title">
          <div className="settings-environment-heading">
            <Cpu size={17} />
            <h2 id="settings-environment-title">Información del entorno</h2>
          </div>
          <dl className="settings-environment-grid">
            <div><dt>Versión del sistema</dt><dd>1.0.0</dd></div>
            <div><dt>Backend</dt><dd>FastAPI + SQLAlchemy 2.0</dd></div>
            <div><dt>Base de datos</dt><dd>PostgreSQL 15 (Docker)</dd></div>
            <div><dt>Motor de inferencia</dt><dd>Ultralytics YOLO26m</dd></div>
            <div><dt>Frontend</dt><dd>React 19 + Vite + TypeScript</dd></div>
          </dl>
        </section>
      </div>
    </div>
  );
};
