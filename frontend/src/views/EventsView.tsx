import React, { useState, useEffect, useCallback } from 'react';
import { getProductionEventsApi, exportProductionEventsCsvApi, associateEventApi, completeProductionUnitApi, getProductionOrdersApi, updateProductionEventApi, deleteProductionEventApi } from '../api/endpoints';
import type { ProductionEvent, ProductionOrder } from '../types';
import { Filter, RefreshCw, Link, Download, ChevronLeft, ChevronRight, CheckCheck, Pencil, Trash2 } from 'lucide-react';
import { confirmProductionEventDeletion, showErrorToast, showSuccessToast } from '../utils/notifications';
import { useAuth } from '../context/useAuth';

const PAGE_SIZE = 50;
const toLocalDateTimeInput = (value: string) => {
  const date = new Date(value);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
};

export const EventsView: React.FC = () => {
  const { user } = useAuth();
  const canOperate = user?.role === 'ADMIN' || user?.role === 'OPERATOR';
  const [events, setEvents] = useState<ProductionEvent[]>([]);
  const [orders, setOrders] = useState<ProductionOrder[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [stageFilter, setStageFilter] = useState('');
  const [associationFilter, setAssociationFilter] = useState('');
  const [syncFilter, setSyncFilter] = useState('');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [page, setPage] = useState(0);
  const [hasNextPage, setHasNextPage] = useState(false);
  const [exporting, setExporting] = useState(false);

  // Associate modal
  const [associatingEvent, setAssociatingEvent] = useState<ProductionEvent | null>(null);
  const [selectedOrderId, setSelectedOrderId] = useState<number | ''>('');
  const [associatingSubmitting, setAssociatingSubmitting] = useState(false);
  const [editingEvent, setEditingEvent] = useState<ProductionEvent | null>(null);
  const [eventForm, setEventForm] = useState({ stage: '', confidence: '', evidence_count: '', event_timestamp: '' });
  const [eventSubmitting, setEventSubmitting] = useState(false);

  const fetchEvents = useCallback(async () => {
    try {
      const [eventsData, ordersData] = await Promise.all([
        getProductionEventsApi({
          skip: page * PAGE_SIZE,
          limit: PAGE_SIZE + 1,
          stage: stageFilter || undefined,
          association_status: associationFilter || undefined,
          sync_status: syncFilter || undefined,
          date_from: dateFrom ? `${dateFrom}T00:00:00+00:00` : undefined,
          date_to: dateTo ? `${dateTo}T23:59:59.999999+00:00` : undefined,
        }),
        getProductionOrdersApi(0, 100)
      ]);
      setHasNextPage(eventsData.length > PAGE_SIZE);
      setEvents(eventsData.slice(0, PAGE_SIZE));
      setOrders(ordersData);
    } catch (err: any) {
      setError(err.message || 'Error cargando historial de eventos');
    } finally {
      setLoading(false);
    }
  }, [page, stageFilter, associationFilter, syncFilter, dateFrom, dateTo]);

  useEffect(() => {
    void Promise.resolve().then(fetchEvents);
  }, [fetchEvents]);

  const handleExport = async () => {
    setExporting(true);
    try {
      const blob = await exportProductionEventsCsvApi({
        stage: stageFilter || undefined,
        association_status: associationFilter || undefined,
        sync_status: syncFilter || undefined,
        date_from: dateFrom ? `${dateFrom}T00:00:00+00:00` : undefined,
        date_to: dateTo ? `${dateTo}T23:59:59.999999+00:00` : undefined,
      });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = 'eventos-produccion.csv';
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (err: any) {
      showErrorToast(err.message || 'Error exportando eventos');
    } finally {
      setExporting(false);
    }
  };

  const handleOpenAssociate = (ev: ProductionEvent) => {
    setAssociatingEvent(ev);
    setSelectedOrderId(orders.length > 0 ? orders[0].id : '');
  };

  const handleAssociate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!associatingEvent || !selectedOrderId) return;
    setAssociatingSubmitting(true);
    try {
      await associateEventApi(associatingEvent.id, Number(selectedOrderId));
      setAssociatingEvent(null);
      fetchEvents();
      showSuccessToast('Evento asociado correctamente.');
    } catch (err: any) {
      showErrorToast(err.message || 'Error al asociar evento');
    } finally {
      setAssociatingSubmitting(false);
    }
  };

  const handleCompleteUnit = async (eventId: number) => {
    try {
      await completeProductionUnitApi(eventId);
      await fetchEvents();
      showSuccessToast('Unidad confirmada y contabilizada en producción.');
    } catch (err: any) {
      showErrorToast(err.message || 'No se pudo confirmar la unidad');
    }
  };

  const handleOpenEdit = (event: ProductionEvent) => {
    setEditingEvent(event);
    setEventForm({
      stage: event.stage,
      confidence: String(event.confidence),
      evidence_count: String(event.evidence_count),
      event_timestamp: toLocalDateTimeInput(event.event_timestamp),
    });
  };

  const handleUpdateEvent = async (formEvent: React.FormEvent) => {
    formEvent.preventDefault();
    if (!editingEvent) return;
    setEventSubmitting(true);
    try {
      await updateProductionEventApi(editingEvent.id, {
        stage: eventForm.stage,
        confidence: Number(eventForm.confidence),
        evidence_count: Number(eventForm.evidence_count),
        event_timestamp: new Date(eventForm.event_timestamp).toISOString(),
      });
      setEditingEvent(null);
      await fetchEvents();
      showSuccessToast('Evento actualizado correctamente.');
    } catch (err: any) {
      showErrorToast(err.message || 'Error actualizando evento');
    } finally {
      setEventSubmitting(false);
    }
  };

  const handleDeleteEvent = async (event: ProductionEvent) => {
    const confirmation = await confirmProductionEventDeletion(event.id);
    if (!confirmation.isConfirmed) return;
    try {
      await deleteProductionEventApi(event.id);
      await fetchEvents();
      showSuccessToast('Evento eliminado.');
    } catch (err: any) {
      showErrorToast(err.message || 'Error eliminando evento');
    }
  };

  return (
    <div className="view-container">
      <div className="view-header">
        <div>
          <h2 style={{ fontSize: '1.25rem', fontWeight: 700, color: '#0f172a' }}>Historial de Eventos de Producción</h2>
          <p style={{ fontSize: '0.85rem', color: '#64748b' }}>
            Eventos confirmados por visión artificial, control de duplicados y asociación a órdenes
          </p>
        </div>
        <button onClick={() => { setLoading(true); setError(null); void fetchEvents(); }} className="btn btn-outline btn-sm">
          <RefreshCw size={14} /> Actualizar
        </button>
      </div>

      {/* Filter Bar */}
      <div className="card" style={{ padding: '16px 20px', marginBottom: '20px' }}>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '16px', alignItems: 'center' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#64748b', fontSize: '0.85rem' }}>
            <Filter size={16} /> Filtros:
          </div>
          <div>
            <select
              className="input-control"
              style={{ width: '200px' }}
              value={stageFilter}
              onChange={(e) => { setPage(0); setStageFilter(e.target.value); }}
            >
              <option value="">Todas las Etapas</option>
              <option value="DOBLADO">Doblado</option>
              <option value="ARMADO_ESTRUCTURAL">Armado estructural</option>
              <option value="VINILADO">Vinilado</option>
              <option value="ALMACEN">Almacén</option>
            </select>
          </div>
          <div>
            <select
              className="input-control"
              style={{ width: '200px' }}
              value={associationFilter}
              onChange={(e) => { setPage(0); setAssociationFilter(e.target.value); }}
            >
              <option value="">Todos los Estados de Asociación</option>
              <option value="PENDIENTE">Pendientes de Asociación</option>
              <option value="ASOCIADO">Asociados a Orden</option>
            </select>
          </div>
          <div>
            <select
              className="input-control"
              style={{ width: '200px' }}
              value={syncFilter}
              onChange={(e) => { setPage(0); setSyncFilter(e.target.value); }}
            >
              <option value="">Todos los Estados de Sync</option>
              <option value="PENDIENTE">Pendientes de Sync Odoo</option>
              <option value="SINCRONIZADO">Sincronizados con Odoo</option>
            </select>
          </div>
          <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: '0.75rem', color: '#475569' }}>
            Desde<input type="date" className="input-control" value={dateFrom} onChange={event => { setPage(0); setDateFrom(event.target.value); }} />
          </label>
          <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: '0.75rem', color: '#475569' }}>
            Hasta<input type="date" className="input-control" value={dateTo} onChange={event => { setPage(0); setDateTo(event.target.value); }} />
          </label>
          <button onClick={() => void handleExport()} disabled={exporting} className="btn btn-outline btn-sm">
            {exporting ? <RefreshCw size={14} className="animate-spin" /> : <Download size={14} />} Exportar CSV
          </button>
        </div>
      </div>

      {error && (
        <div style={{ backgroundColor: '#fee2e2', color: '#b91c1c', padding: '12px', borderRadius: '6px', marginBottom: '16px' }}>
          {error}
        </div>
      )}

      {/* Events Table */}
      <div className="card">
        {events.length === 0 && !loading ? (
          <div style={{ textAlign: 'center', padding: '48px 20px', color: '#94a3b8' }}>
            No se encontraron eventos registrados con los filtros seleccionados.
          </div>
        ) : (
          <div className="table-responsive">
            <table>
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Fecha/Hora Evento</th>
                  <th>Etapa Productiva</th>
                  <th>Cámara / Zona</th>
                  <th>Confianza</th>
                  <th>Orden Asociada</th>
                  <th>Asociación</th>
                  <th>Sincronización Odoo</th>
                  <th>Acciones</th>
                </tr>
              </thead>
              <tbody>
                {events.map((ev) => (
                  <tr key={ev.id}>
                    <td>#{ev.id}</td>
                    <td>{new Date(ev.event_timestamp).toLocaleString()}</td>
                    <td><strong>{ev.stage}</strong></td>
                    <td>{ev.camera_name || `Cámara #${ev.camera_id}`}</td>
                    <td>{(ev.confidence * 100).toFixed(1)}%</td>
                    <td>
                      {ev.order_name ? (
                        <span style={{ fontWeight: 600, color: 'var(--primary)' }}>{ev.order_name}</span>
                      ) : (
                        <span style={{ color: '#94a3b8', fontSize: '0.8rem' }}>Sin asociar</span>
                      )}
                    </td>
                    <td>
                      <span className={`badge ${
                        ev.association_status === 'ASOCIADO' ? 'badge-success' : 'badge-warning'
                      }`}>
                        {ev.association_status}
                      </span>
                    </td>
                    <td>
                      <span className={`badge ${
                        ev.sync_status === 'SINCRONIZADO' ? 'badge-success' : 'badge-info'
                      }`}>
                        {ev.sync_status}
                      </span>
                    </td>
                    <td>
                      {user?.role === 'ADMIN' && (
                        <div style={{ display: 'flex', gap: 6, marginBottom: canOperate ? 6 : 0 }}>
                          <button onClick={() => handleOpenEdit(ev)} className="btn btn-outline btn-sm" title="Editar evento" aria-label={`Editar evento ${ev.id}`}><Pencil size={13} /></button>
                          <button onClick={() => void handleDeleteEvent(ev)} className="btn btn-outline btn-sm" title="Eliminar evento" aria-label={`Eliminar evento ${ev.id}`}><Trash2 size={13} /></button>
                        </div>
                      )}
                      {canOperate && ev.association_status === 'PENDIENTE' && (
                        <button
                          onClick={() => handleOpenAssociate(ev)}
                          className="btn btn-outline btn-sm"
                        >
                          <Link size={12} /> Asociar Orden
                        </button>
                      )}
                      {canOperate && ev.association_status === 'ASOCIADO' && ev.stage === 'VINILADO' && ev.event_type !== 'FIN_PRODUCTO' && (
                        <button onClick={() => void handleCompleteUnit(ev.id)} className="btn btn-outline btn-sm">
                          <CheckCheck size={12} /> Confirmar unidad
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div style={{ display: 'flex', justifyContent: 'flex-end', alignItems: 'center', gap: 10, marginTop: 12 }}>
        <span style={{ fontSize: '0.8rem', color: '#64748b' }}>Página {page + 1}</span>
        <button className="btn btn-outline btn-sm" disabled={page === 0 || loading} onClick={() => setPage(current => Math.max(0, current - 1))} aria-label="Página anterior"><ChevronLeft size={15} /> Anterior</button>
        <button className="btn btn-outline btn-sm" disabled={!hasNextPage || loading} onClick={() => setPage(current => current + 1)} aria-label="Página siguiente">Siguiente <ChevronRight size={15} /></button>
      </div>

      {editingEvent && (
        <div className="modal-overlay" onClick={() => setEditingEvent(null)}>
          <div className="modal-content" onClick={event => event.stopPropagation()}>
            <div className="card-header">
              <h3 className="card-title">Editar evento #{editingEvent.id}</h3>
              <button onClick={() => setEditingEvent(null)} className="btn btn-outline btn-sm" aria-label="Cerrar">✕</button>
            </div>
            <form onSubmit={handleUpdateEvent} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              <label>Etapa
                <select className="input-control" value={eventForm.stage} onChange={event => setEventForm(current => ({ ...current, stage: event.target.value }))}>
                  <option value="DOBLADO">Doblado</option>
                  <option value="ARMADO_ESTRUCTURAL">Armado estructural</option>
                  <option value="VINILADO">Vinilado</option>
                  <option value="ALMACEN">Almacén</option>
                  <option value="NO_IDENTIFICADO">No identificado</option>
                </select>
              </label>
              <label>Fecha y hora
                <input type="datetime-local" className="input-control" required value={eventForm.event_timestamp} onChange={event => setEventForm(current => ({ ...current, event_timestamp: event.target.value }))} />
              </label>
              <label>Confianza (0 a 1)
                <input type="number" min="0" max="1" step="0.001" className="input-control" required value={eventForm.confidence} onChange={event => setEventForm(current => ({ ...current, confidence: event.target.value }))} />
              </label>
              <label>Evidencias
                <input type="number" min="1" step="1" className="input-control" required value={eventForm.evidence_count} onChange={event => setEventForm(current => ({ ...current, evidence_count: event.target.value }))} />
              </label>
              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
                <button type="button" className="btn btn-outline" onClick={() => setEditingEvent(null)}>Cancelar</button>
                <button type="submit" className="btn btn-primary" disabled={eventSubmitting}>{eventSubmitting ? 'Guardando...' : 'Guardar cambios'}</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Associate Modal */}
      {associatingEvent && (
        <div className="modal-overlay" onClick={() => setAssociatingEvent(null)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="card-header">
              <h3 className="card-title">Asociar Evento #{associatingEvent.id} a Orden</h3>
              <button onClick={() => setAssociatingEvent(null)} className="btn btn-outline btn-sm">✕</button>
            </div>

            <div style={{ backgroundColor: '#f8fafc', padding: '12px', borderRadius: '6px', marginBottom: '16px', fontSize: '0.85rem' }}>
              <div>Etapa detectada: <strong>{associatingEvent.stage}</strong></div>
              <div>Cámara: {associatingEvent.camera_name || `Cámara #${associatingEvent.camera_id}`}</div>
              <div>Fecha: {new Date(associatingEvent.event_timestamp).toLocaleString()}</div>
            </div>

            {orders.length === 0 ? (
              <p style={{ color: '#d97706', fontSize: '0.85rem' }}>
                No hay órdenes de producción disponibles. Crea una orden primero en la sección de Producción.
              </p>
            ) : (
              <form onSubmit={handleAssociate} style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
                <div>
                  <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, marginBottom: '6px' }}>
                    Seleccione la orden de fabricación de destino
                  </label>
                  <select
                    className="input-control"
                    value={selectedOrderId}
                    onChange={(e) => setSelectedOrderId(Number(e.target.value))}
                    required
                  >
                    {orders.map((o) => (
                      <option key={o.id} value={o.id}>
                        {o.name} - {o.product_name} ({o.state})
                      </option>
                    ))}
                  </select>
                </div>

                <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px', marginTop: '12px' }}>
                  <button type="button" onClick={() => setAssociatingEvent(null)} className="btn btn-outline">
                    Cancelar
                  </button>
                  <button type="submit" disabled={associatingSubmitting} className="btn btn-primary">
                    {associatingSubmitting ? 'Guardando...' : 'Confirmar Asociación'}
                  </button>
                </div>
              </form>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
