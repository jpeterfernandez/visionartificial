import React, { useState, useEffect } from 'react';
import { getOdooConfigApi, getOdooStatusApi, syncOdooOrdersApi, syncOdooEventsApi, updateOdooConfigApi } from '../api/endpoints';
import type { OdooConfig, OdooConfigUpdate, OdooStatus } from '../types';
import { Link2, RefreshCw, AlertTriangle, ArrowDownCircle, ArrowUpCircle, Save } from 'lucide-react';
import { showErrorToast, showSuccessToast } from '../utils/notifications';
import { useAuth } from '../context/useAuth';

export const OdooView: React.FC = () => {
  const { user } = useAuth();
  const [status, setStatus] = useState<OdooStatus | null>(null);
  const [statusLoading, setStatusLoading] = useState(true);
  const [config, setConfig] = useState<OdooConfig | null>(null);
  const [configForm, setConfigForm] = useState<OdooConfigUpdate>({
    base_url: '',
    database: '',
    username: '',
    timeout: 10,
    api_key: '',
  });
  const [configLoading, setConfigLoading] = useState(false);
  const [savingConfig, setSavingConfig] = useState(false);
  const [clearApiKey, setClearApiKey] = useState(false);
  const [syncingOrders, setSyncingOrders] = useState(false);
  const [syncingEvents, setSyncingEvents] = useState(false);

  const fetchStatus = async () => {
    try {
      const data = await getOdooStatusApi();
      setStatus(data);
    } catch (err: any) {
      showErrorToast(err.message || 'Error verificando estado de Odoo');
    } finally {
      setStatusLoading(false);
    }
  };

  const fetchConfig = async () => {
    try {
      const data = await getOdooConfigApi();
      setConfig(data);
      setConfigForm({
        base_url: data.base_url,
        database: data.database,
        username: data.username,
        timeout: data.timeout,
        api_key: '',
      });
    } catch (err: any) {
      showErrorToast(err.message || 'Error cargando los parámetros de Odoo');
    } finally {
      setConfigLoading(false);
    }
  };

  useEffect(() => {
    void Promise.resolve().then(() => {
      void fetchStatus();
      if (user?.role === 'ADMIN') void fetchConfig();
    });
  }, [user]);

  const handleSaveConfig = async () => {
    setSavingConfig(true);
    try {
      const payload: OdooConfigUpdate = {
        base_url: configForm.base_url.trim(),
        database: configForm.database.trim(),
        username: configForm.username.trim(),
        timeout: Number(configForm.timeout),
        clear_api_key: clearApiKey,
      };
      if (configForm.api_key?.trim() && !clearApiKey) payload.api_key = configForm.api_key;

      const saved = await updateOdooConfigApi(payload);
      setConfig(saved);
      setConfigForm({
        base_url: saved.base_url,
        database: saved.database,
        username: saved.username,
        timeout: saved.timeout,
        api_key: '',
      });
      setClearApiKey(false);
      setStatus(current => current ? {
        ...current,
        enabled: saved.enabled,
        configured: saved.api_key_configured && Boolean(saved.base_url && saved.database && saved.username),
        base_url: saved.base_url,
        database: saved.database,
        username: saved.username,
        connected: false,
        authenticated: false,
        server_version: null,
      } : current);
      showSuccessToast('Configuración de Odoo guardada en el servidor.');
    } catch (err: any) {
      showErrorToast(err.message || 'Error guardando la configuración de Odoo');
    } finally {
      setSavingConfig(false);
    }
  };

  const handleSyncOrders = async () => {
    setSyncingOrders(true);
    try {
      const res = await syncOdooOrdersApi();
      showSuccessToast(`Sincronización completada: ${res.new_orders} nuevas, ${res.updated_orders} actualizadas.`);
    } catch (err: any) {
      showErrorToast(`Error en sincronización: ${err.message}`);
    } finally {
      setSyncingOrders(false);
    }
  };

  const handleSyncEvents = async () => {
    setSyncingEvents(true);
    try {
      const res = await syncOdooEventsApi();
      showSuccessToast(res.message || 'Sincronización de eventos completada');
    } catch (err: any) {
      showErrorToast(`Error en sincronización: ${err.message}`);
    } finally {
      setSyncingEvents(false);
    }
  };

  return (
    <div className="view-container">
      <div className="view-header">
        <div>
          <h2 style={{ fontSize: '1.25rem', fontWeight: 700, color: '#0f172a' }}>Integración con Odoo ERP</h2>
          <p style={{ fontSize: '0.85rem', color: '#64748b' }}>
            Conexión con el módulo de fabricación (mrp.production) y sincronización bidireccional segura
          </p>
        </div>
        <button onClick={() => { setStatusLoading(true); void fetchStatus(); }} disabled={statusLoading || !status?.enabled} className="btn btn-outline btn-sm">
          <RefreshCw size={14} /> Probar Conectividad
        </button>
      </div>

      {user?.role === 'ADMIN' && (
        <div className="card" style={{ marginBottom: '24px' }}>
          <div className="card-header">
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <Link2 size={20} style={{ color: 'var(--primary)' }} />
              <h3 className="card-title">Configuración de la vinculación</h3>
            </div>
          </div>
          <p style={{ fontSize: '0.82rem', color: '#64748b', marginBottom: '16px' }}>
            Estos valores se guardan en el servidor y se usan en las conexiones nuevas. La clave API nunca se muestra.
          </p>
          {configLoading || !config ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#64748b', fontSize: '0.85rem' }}>
              <RefreshCw className="animate-spin" size={15} /> Cargando parámetros...
            </div>
          ) : (
            <div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '16px' }}>
                <label style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                  <span style={{ fontSize: '0.8rem', fontWeight: 600 }}>URL del servidor</span>
                  <input className="input-control" type="url" value={configForm.base_url} onChange={event => setConfigForm(current => ({ ...current, base_url: event.target.value }))} />
                </label>
                <label style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                  <span style={{ fontSize: '0.8rem', fontWeight: 600 }}>Base de datos</span>
                  <input className="input-control" value={configForm.database} onChange={event => setConfigForm(current => ({ ...current, database: event.target.value }))} />
                </label>
                <label style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                  <span style={{ fontSize: '0.8rem', fontWeight: 600 }}>Usuario</span>
                  <input className="input-control" autoComplete="username" value={configForm.username} onChange={event => setConfigForm(current => ({ ...current, username: event.target.value }))} />
                </label>
                <label style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                  <span style={{ fontSize: '0.8rem', fontWeight: 600 }}>Tiempo de espera (segundos)</span>
                  <input className="input-control" type="number" min={1} max={120} value={configForm.timeout} onChange={event => setConfigForm(current => ({ ...current, timeout: Number(event.target.value) }))} />
                </label>
                <label style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                  <span style={{ fontSize: '0.8rem', fontWeight: 600 }}>Clave API</span>
                  <input
                    className="input-control"
                    type="password"
                    autoComplete="new-password"
                    placeholder={config.api_key_configured ? 'Configurada; vacía conserva la actual' : 'Introduce la clave API'}
                    value={configForm.api_key || ''}
                    disabled={clearApiKey}
                    onChange={event => setConfigForm(current => ({ ...current, api_key: event.target.value }))}
                  />
                </label>
              </div>
              {config.api_key_configured && (
                <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.82rem', marginTop: '14px' }}>
                  <input type="checkbox" checked={clearApiKey} onChange={event => setClearApiKey(event.target.checked)} />
                  Eliminar la clave API guardada
                </label>
              )}
              <button type="button" onClick={handleSaveConfig} disabled={savingConfig || configLoading} className="btn btn-primary" style={{ marginTop: '16px' }}>
                {savingConfig ? <RefreshCw className="animate-spin" size={16} /> : <Save size={16} />}
                Guardar configuración
              </button>
            </div>
          )}
        </div>
      )}

      {/* Connection Status Card */}
      <div className="card">
        <div className="card-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <Link2 size={20} style={{ color: 'var(--primary)' }} />
            <h3 className="card-title">Parámetros de Conexión ERP</h3>
          </div>
          {status && (
            <span className={`badge ${!status.enabled ? 'badge-info' : status.connected && status.authenticated ? 'badge-success' : 'badge-warning'}`}>
              {!status.enabled ? 'Integración desactivada' : status.connected && status.authenticated ? 'Conectado y Autenticado' : 'Sin enlace activo'}
            </span>
          )}
        </div>

        {status && (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: '16px' }}>
            <div>
              <span style={{ fontSize: '0.8rem', color: '#64748b' }}>URL del Servidor Odoo:</span>
              <div style={{ fontWeight: 600 }}>{status.base_url || 'No especificada'}</div>
            </div>
            <div>
              <span style={{ fontSize: '0.8rem', color: '#64748b' }}>Base de Datos Odoo:</span>
              <div style={{ fontWeight: 600 }}>{status.database || 'No especificada'}</div>
            </div>
            <div>
              <span style={{ fontSize: '0.8rem', color: '#64748b' }}>Usuario del Servicio:</span>
              <div style={{ fontWeight: 600 }}>{status.username || 'No especificado'}</div>
            </div>
            <div>
              <span style={{ fontSize: '0.8rem', color: '#64748b' }}>Versión del Servidor ERP:</span>
              <div style={{ fontWeight: 600 }}>{status.server_version || 'No disponible'}</div>
            </div>
          </div>
        )}

        {status?.error && (
          <div style={{
            marginTop: '16px',
            padding: '12px',
            backgroundColor: '#fffbeb',
            border: '1px solid #fef3c7',
            borderRadius: '6px',
            fontSize: '0.85rem',
            color: '#b45309',
            display: 'flex',
            alignItems: 'center',
            gap: '8px'
          }}>
            <AlertTriangle size={16} />
            <span>Diagnóstico: {status.error}</span>
          </div>
        )}
      </div>

      {/* Synchronization Actions */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))', gap: '24px' }}>
        {/* Pull Orders */}
        <div className="card">
          <div className="card-header">
            <h3 className="card-title">Consultar Órdenes de Fabricación</h3>
          </div>
          <p style={{ fontSize: '0.85rem', color: '#64748b', marginBottom: '16px' }}>
            Importa o actualiza las órdenes de producción desde <code>mrp.production</code> hacia la base de datos PostgreSQL local de forma idempotente.
          </p>
          <button
            onClick={handleSyncOrders}
            disabled={syncingOrders || status?.enabled !== true}
            className="btn btn-outline"
            style={{ width: '100%' }}
          >
            {syncingOrders ? (
              <RefreshCw className="animate-spin" size={16} />
            ) : (
              <ArrowDownCircle size={16} />
            )}
            Sincronizar Órdenes de Odoo
          </button>
        </div>

        {/* Push Events */}
        <div className="card">
          <div className="card-header">
            <h3 className="card-title">Sincronizar Eventos Confirmados</h3>
          </div>
          <p style={{ fontSize: '0.85rem', color: '#64748b', marginBottom: '16px' }}>
            Transmite eventos de visión confirmados y asociados a órdenes pendientes de sincronización. Si Odoo está apagado, los eventos se preservan localmente sin pérdida.
          </p>
          <button
            onClick={handleSyncEvents}
            disabled={syncingEvents || status?.enabled !== true}
            className="btn btn-outline"
            style={{ width: '100%' }}
          >
            {syncingEvents ? (
              <RefreshCw className="animate-spin" size={16} />
            ) : (
              <ArrowUpCircle size={16} />
            )}
            Transmitir Eventos Pendientes
          </button>
        </div>
      </div>
    </div>
  );
};
