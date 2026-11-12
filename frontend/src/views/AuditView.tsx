import React, { useEffect, useState } from 'react';
import { ChevronLeft, ChevronRight, Download, RefreshCw, ShieldCheck } from 'lucide-react';
import { exportAuditCsvApi, getAuditLogsApi } from '../api/endpoints';
import type { AuditLog } from '../types';
import { useAuth } from '../context/useAuth';

const PAGE_SIZE = 100;

export const AuditView: React.FC = () => {
  const { user } = useAuth();
  const [entries, setEntries] = useState<AuditLog[]>([]);
  const [page, setPage] = useState(0);
  const [refreshKey, setRefreshKey] = useState(0);
  const [loading, setLoading] = useState(true);
  const [hasNext, setHasNext] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);

  const handleExport = async () => {
    setExporting(true);
    try {
      const blob = await exportAuditCsvApi();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = 'auditoria.csv';
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'No se pudo exportar la auditoría');
    } finally {
      setExporting(false);
    }
  };

  useEffect(() => {
    let active = true;
    Promise.resolve().then(() => getAuditLogsApi(page * PAGE_SIZE, PAGE_SIZE + 1))
      .then(data => {
        if (!active) return;
        setHasNext(data.length > PAGE_SIZE);
        setEntries(data.slice(0, PAGE_SIZE));
        setError(null);
      })
      .catch(reason => {
        if (active) setError(reason instanceof Error ? reason.message : 'No se pudo cargar la auditoría');
      })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [page, refreshKey]);

  if (user?.role !== 'ADMIN') return <div className="view-container"><h2>Acceso restringido</h2></div>;

  return (
    <div className="view-container">
      <div className="view-header">
        <div>
          <h2 style={{ fontSize: '1.25rem', fontWeight: 700, color: '#0f172a' }}>Auditoría</h2>
          <p style={{ fontSize: '0.85rem', color: '#64748b' }}>Cambios administrativos y operaciones de producción</p>
        </div>
        <button className="btn btn-outline btn-sm" disabled={loading} onClick={() => { setLoading(true); setRefreshKey(current => current + 1); }}>
          <RefreshCw size={14} /> Actualizar
        </button>
        <button className="btn btn-outline btn-sm" disabled={exporting} onClick={() => void handleExport()}>
          {exporting ? <RefreshCw size={14} className="animate-spin" /> : <Download size={14} />} Exportar CSV
        </button>
      </div>
      {error && <div role="alert" className="card" style={{ color: '#b91c1c' }}>{error}</div>}
      <div className="card">
        {loading && entries.length === 0 ? <p>Cargando historial...</p> : entries.length === 0 ? <p>No hay acciones registradas.</p> : (
          <div className="table-responsive">
            <table>
              <thead><tr><th>Fecha</th><th>Usuario</th><th>Acción</th><th>Objetivo</th><th>Detalles</th></tr></thead>
              <tbody>{entries.map(entry => (
                <tr key={entry.id}>
                  <td>{new Date(entry.created_at).toLocaleString()}</td>
                  <td>{entry.actor_username}</td>
                  <td><ShieldCheck size={14} style={{ verticalAlign: 'middle', marginRight: 5 }} />{entry.action}</td>
                  <td>{entry.target_type}{entry.target_id ? ` #${entry.target_id}` : ''}</td>
                  <td><code>{entry.details ? JSON.stringify(entry.details) : ''}</code></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        )}
      </div>
      <div style={{ display: 'flex', justifyContent: 'flex-end', alignItems: 'center', gap: 10, marginTop: 12 }}>
        <span style={{ fontSize: '0.8rem', color: '#64748b' }}>Página {page + 1}</span>
        <button className="btn btn-outline btn-sm" disabled={page === 0 || loading} onClick={() => { setLoading(true); setPage(current => Math.max(0, current - 1)); }}><ChevronLeft size={15} /> Anterior</button>
        <button className="btn btn-outline btn-sm" disabled={!hasNext || loading} onClick={() => { setLoading(true); setPage(current => current + 1); }}>Siguiente <ChevronRight size={15} /></button>
      </div>
    </div>
  );
};
