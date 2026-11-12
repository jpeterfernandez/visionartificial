import React, { useState, useEffect, useCallback } from 'react';
import { getProductionOrdersApi, exportProductionOrdersCsvApi, createProductionOrderApi, getOrderTimelineApi, updateProductionOrderApi, deleteProductionOrderApi } from '../api/endpoints';
import type { ProductionOrder } from '../types';
import { Plus, Filter, Clock, RefreshCw, Download, Pencil, Trash2 } from 'lucide-react';
import { confirmProductionOrderDeletion, showErrorToast, showSuccessToast } from '../utils/notifications';
import { useAuth } from '../context/useAuth';

const DEFAULT_ZONES = ['DOBLADO', 'ARMADO_ESTRUCTURAL', 'VINILADO', 'ALMACEN'];

export const ProductionView: React.FC = () => {
  const { user } = useAuth();
  const [orders, setOrders] = useState<ProductionOrder[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [stateFilter, setStateFilter] = useState<string>('');
  const [stageFilter, setStageFilter] = useState<string>('');

  // Timeline modal
  const [selectedOrder, setSelectedOrder] = useState<ProductionOrder | null>(null);
  const [timelineData, setTimelineData] = useState<any | null>(null);
  const [loadingTimeline, setLoadingTimeline] = useState(false);

  // New order modal
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [newOrderName, setNewOrderName] = useState('');
  const [newOrderProduct, setNewOrderProduct] = useState('');
  const [newOrderQty, setNewOrderQty] = useState('');
  const [newOrderZone, setNewOrderZone] = useState('');
  const [createSubmitting, setCreateSubmitting] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [editingOrder, setEditingOrder] = useState<ProductionOrder | null>(null);
  const [editForm, setEditForm] = useState({ name: '', product_name: '', zone: '', target_qty: '', produced_qty: '', state: '', current_stage: '', notes: '' });
  const [editSubmitting, setEditSubmitting] = useState(false);

  const fetchOrders = useCallback(async () => {
    try {
      const data = await getProductionOrdersApi(0, 50, stateFilter || undefined, stageFilter || undefined);
      setOrders(data);
    } catch (err: any) {
      setError(err.message || 'Error al consultar órdenes');
    } finally {
      setLoading(false);
    }
  }, [stateFilter, stageFilter]);

  useEffect(() => {
    void Promise.resolve().then(fetchOrders);
  }, [fetchOrders]);

  const handleOpenTimeline = async (order: ProductionOrder) => {
    setSelectedOrder(order);
    setLoadingTimeline(true);
    setTimelineData(null);
    try {
      const data = await getOrderTimelineApi(order.id);
      setTimelineData(data);
    } catch (err: any) {
      showErrorToast(err.message || 'Error cargando historial de la orden');
    } finally {
      setLoadingTimeline(false);
    }
  };

  const handleExport = async () => {
    setExporting(true);
    try {
      const blob = await exportProductionOrdersCsvApi(stateFilter || undefined, stageFilter || undefined);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = 'ordenes-produccion.csv';
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (err: any) {
      showErrorToast(err.message || 'Error exportando órdenes');
    } finally {
      setExporting(false);
    }
  };

  const handleCreateOrder = async (e: React.FormEvent) => {
    e.preventDefault();
    setCreateSubmitting(true);
    try {
      await createProductionOrderApi({
        name: newOrderName,
        product_name: newOrderProduct,
        zone: newOrderZone,
        target_qty: Number(newOrderQty),
      });
      setShowCreateModal(false);
      setNewOrderName('');
      setNewOrderProduct('');
      setNewOrderQty('');
      setNewOrderZone('');
      fetchOrders();
      showSuccessToast('Orden creada correctamente.');
    } catch (err: any) {
      showErrorToast(err.message || 'Error creando orden');
    } finally {
      setCreateSubmitting(false);
    }
  };

  const handleOpenEdit = (order: ProductionOrder) => {
    setEditingOrder(order);
    setEditForm({
      name: order.name,
      product_name: order.product_name,
      zone: order.zone || '',
      target_qty: String(order.target_qty),
      produced_qty: String(order.produced_qty),
      state: order.state,
      current_stage: order.current_stage || '',
      notes: order.notes || '',
    });
  };

  const handleUpdateOrder = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!editingOrder) return;
    setEditSubmitting(true);
    try {
      await updateProductionOrderApi(editingOrder.id, {
        ...editForm,
        target_qty: Number(editForm.target_qty),
        produced_qty: Number(editForm.produced_qty),
        current_stage: editForm.current_stage || null,
        notes: editForm.notes || null,
      });
      setEditingOrder(null);
      await fetchOrders();
      showSuccessToast('Registro de producción actualizado.');
    } catch (error: any) {
      showErrorToast(error.message || 'Error actualizando la orden');
    } finally {
      setEditSubmitting(false);
    }
  };

  const handleDeleteOrder = async (order: ProductionOrder) => {
    const confirmation = await confirmProductionOrderDeletion(order.name);
    if (!confirmation.isConfirmed) return;
    try {
      await deleteProductionOrderApi(order.id);
      await fetchOrders();
      showSuccessToast('Orden eliminada. El historial de eventos se conservó.');
    } catch (error: any) {
      showErrorToast(error.message || 'Error eliminando la orden');
    }
  };

  return (
    <div className="view-container">
      <div className="view-header">
        <div>
          <h2 style={{ fontSize: '1.25rem', fontWeight: 700, color: '#0f172a' }}>Órdenes de Fabricación</h2>
          <p style={{ fontSize: '0.85rem', color: '#64748b' }}>
            Control y seguimiento de unidades a través de las etapas productivas
          </p>
        </div>
        <div style={{ display: 'flex', gap: '8px' }}>
          {(user?.role === 'ADMIN' || user?.role === 'OPERATOR') && <button onClick={() => { setNewOrderZone(user?.role === 'ADMIN' ? DEFAULT_ZONES[0] : user?.allowed_zones[0] || ''); setShowCreateModal(true); }} className="btn btn-primary btn-sm"><Plus size={14} /> Nueva Orden</button>}
          <button onClick={fetchOrders} className="btn btn-outline btn-sm">
            <RefreshCw size={14} /> Actualizar
          </button>
          <button onClick={() => void handleExport()} disabled={exporting} className="btn btn-outline btn-sm">
            {exporting ? <RefreshCw size={14} className="animate-spin" /> : <Download size={14} />} Exportar CSV
          </button>
        </div>
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
              style={{ width: '180px' }}
              value={stateFilter}
              onChange={(e) => setStateFilter(e.target.value)}
            >
              <option value="">Todos los Estados</option>
              <option value="draft">Borrador / Pendiente</option>
              <option value="progress">En Producción</option>
              <option value="done">Finalizado</option>
            </select>
          </div>
          <div>
            <select
              className="input-control"
              style={{ width: '220px' }}
              value={stageFilter}
              onChange={(e) => setStageFilter(e.target.value)}
            >
              <option value="">Todas las Etapas</option>
              <option value="DOBLADO">1. Doblado</option>
              <option value="ARMADO_ESTRUCTURAL">2. Armado estructural</option>
              <option value="VINILADO">3. Vinilado</option>
              <option value="ALMACEN">4. Almacén</option>
            </select>
          </div>
        </div>
      </div>

      {error && (
        <div style={{ backgroundColor: '#fee2e2', color: '#b91c1c', padding: '12px', borderRadius: '6px', marginBottom: '16px' }}>
          {error}
        </div>
      )}

      {/* Orders Table */}
      <div className="card">
        {orders.length === 0 && !loading ? (
          <div style={{ textAlign: 'center', padding: '48px 20px', color: '#94a3b8' }}>
            No se encontraron órdenes registradas con los filtros aplicados.
          </div>
        ) : (
          <div className="table-responsive">
            <table>
              <thead>
                <tr>
                  <th>Referencia</th>
                  <th>Zona</th>
                  <th>Producto / Chasis</th>
                  <th>Estado</th>
                  <th>Etapa Actual (Visión)</th>
                  <th>Cant. Prod. / Objetivo</th>
                  <th>Origen Odoo</th>
                  <th>Última Actualización</th>
                  <th>Acciones</th>
                </tr>
              </thead>
              <tbody>
                {orders.map((o) => (
                  <tr key={o.id}>
                    <td><strong>{o.name}</strong></td>
                    <td>{o.zone || 'Sin asignar'}</td>
                    <td>{o.product_name}</td>
                    <td>
                      <span className={`badge ${
                        o.state === 'done' ? 'badge-success' : o.state === 'progress' ? 'badge-info' : 'badge-warning'
                      }`}>
                        {o.state}
                      </span>
                    </td>
                    <td>
                      {o.current_stage ? (
                        <span className="badge badge-info" style={{ backgroundColor: 'var(--primary-light)', color: 'var(--primary)' }}>
                          {o.current_stage}
                        </span>
                      ) : (
                        <span style={{ color: '#94a3b8', fontSize: '0.8rem' }}>Sin etapa confirmada</span>
                      )}
                    </td>
                    <td>{o.produced_qty} / {o.target_qty}</td>
                    <td>
                      {o.odoo_order_id ? (
                        <span style={{ fontSize: '0.8rem', color: '#16a34a' }}>Odoo #{o.odoo_order_id}</span>
                      ) : (
                        <span style={{ fontSize: '0.8rem', color: '#64748b' }}>Manual</span>
                      )}
                    </td>
                    <td>{new Date(o.updated_at).toLocaleDateString()}</td>
                    <td>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                        <button onClick={() => handleOpenTimeline(o)} className="btn btn-outline btn-sm"><Clock size={12} /> Línea de Tiempo</button>
                        {user?.role === 'ADMIN' && <>
                          <button onClick={() => handleOpenEdit(o)} className="btn btn-outline btn-sm" title="Editar orden" aria-label={`Editar orden ${o.name}`}><Pencil size={13} /></button>
                          <button onClick={() => void handleDeleteOrder(o)} className="btn btn-outline btn-sm" title="Eliminar orden" aria-label={`Eliminar orden ${o.name}`}><Trash2 size={13} /></button>
                        </>}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Timeline Modal */}
      {selectedOrder && (
        <div className="modal-overlay" onClick={() => setSelectedOrder(null)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()} style={{ maxWidth: '640px' }}>
            <div className="card-header">
              <h3 className="card-title">Historial y Tiempos: {selectedOrder.name}</h3>
              <button onClick={() => setSelectedOrder(null)} className="btn btn-outline btn-sm">✕</button>
            </div>

            <div style={{ marginBottom: '16px', fontSize: '0.85rem', color: '#64748b' }}>
              Producto: <strong>{selectedOrder.product_name}</strong> | Estado: {selectedOrder.state}
            </div>

            {loadingTimeline ? (
              <div style={{ textAlign: 'center', padding: '30px' }}>
                <RefreshCw className="animate-spin" size={24} style={{ color: 'var(--primary)' }} />
                <p style={{ marginTop: '8px', fontSize: '0.85rem' }}>Calculando duraciones de etapas...</p>
              </div>
            ) : timelineData && timelineData.timeline.length === 0 ? (
              <div style={{ textAlign: 'center', padding: '36px', color: '#94a3b8' }}>
                No existen eventos confirmados asociados a esta orden todavía.
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                {timelineData?.timeline.map((item: any, idx: number) => (
                  <div
                    key={idx}
                    style={{
                      borderLeft: '3px solid var(--primary)',
                      padding: '8px 14px',
                      backgroundColor: '#f8fafc',
                      borderRadius: '0 6px 6px 0'
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <span style={{ fontWeight: 600, fontSize: '0.9rem' }}>{item.stage}</span>
                      <span style={{ fontSize: '0.75rem', color: '#64748b' }}>
                        {new Date(item.timestamp).toLocaleString()}
                      </span>
                    </div>
                    <div style={{ fontSize: '0.8rem', color: '#64748b', marginTop: '4px' }}>
                      Confianza: {(item.confidence * 100).toFixed(1)}% | Cámara #{item.camera_id}
                      {item.duration_minutes !== null && (
                        <span style={{ marginLeft: '12px', color: 'var(--primary)', fontWeight: 600 }}>
                          Duración calculada a siguiente etapa: {item.duration_minutes} min
                        </span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Create Order Modal */}
      {showCreateModal && (
        <div className="modal-overlay" onClick={() => setShowCreateModal(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="card-header">
              <h3 className="card-title">Registrar Nueva Orden de Producción</h3>
              <button onClick={() => setShowCreateModal(false)} className="btn btn-outline btn-sm">✕</button>
            </div>

            <form onSubmit={handleCreateOrder} style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
              <div>
                <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, marginBottom: '6px' }}>Zona de producción</label>
                <select className="input-control" value={newOrderZone} onChange={event => setNewOrderZone(event.target.value)} required>
                  <option value="" disabled>Seleccione una zona</option>
                  {(user?.role === 'ADMIN' ? DEFAULT_ZONES : user?.allowed_zones || []).map(zone => <option key={zone} value={zone}>{zone}</option>)}
                </select>
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, marginBottom: '6px' }}>
                  Código / Referencia de la Orden
                </label>
                <input
                  type="text"
                  className="input-control"
                  value={newOrderName}
                  onChange={(e) => setNewOrderName(e.target.value)}
                  required
                />
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, marginBottom: '6px' }}>
                  Nombre del Producto / Chasis
                </label>
                <input
                  type="text"
                  className="input-control"
                  value={newOrderProduct}
                  onChange={(e) => setNewOrderProduct(e.target.value)}
                  required
                />
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, marginBottom: '6px' }}>
                  Cantidad Objetivo
                </label>
                <input
                  type="number"
                  min="1"
                  className="input-control"
                  value={newOrderQty}
                  onChange={(e) => setNewOrderQty(e.target.value)}
                  required
                />
              </div>

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px', marginTop: '12px' }}>
                <button type="button" onClick={() => setShowCreateModal(false)} className="btn btn-outline">
                  Cancelar
                </button>
                <button type="submit" disabled={createSubmitting} className="btn btn-primary">
                  {createSubmitting ? 'Guardando...' : 'Crear Orden'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {editingOrder && (
        <div className="modal-overlay" onClick={() => setEditingOrder(null)}>
          <div className="modal-content" onClick={event => event.stopPropagation()}>
            <div className="card-header">
              <h3 className="card-title">Editar orden {editingOrder.name}</h3>
              <button onClick={() => setEditingOrder(null)} className="btn btn-outline btn-sm" aria-label="Cerrar">✕</button>
            </div>
            <form onSubmit={handleUpdateOrder} style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              <label>Referencia<input className="input-control" required maxLength={100} value={editForm.name} onChange={event => setEditForm(current => ({ ...current, name: event.target.value }))} /></label>
              <label>Producto / Chasis<input className="input-control" required maxLength={200} value={editForm.product_name} onChange={event => setEditForm(current => ({ ...current, product_name: event.target.value }))} /></label>
              <label>Zona<input className="input-control" maxLength={50} value={editForm.zone} onChange={event => setEditForm(current => ({ ...current, zone: event.target.value }))} /></label>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                <label>Cantidad objetivo<input type="number" min="1" className="input-control" required value={editForm.target_qty} onChange={event => setEditForm(current => ({ ...current, target_qty: event.target.value }))} /></label>
                <label>Producidas<input type="number" min="0" className="input-control" required value={editForm.produced_qty} onChange={event => setEditForm(current => ({ ...current, produced_qty: event.target.value }))} /></label>
              </div>
              <label>Estado<select className="input-control" value={editForm.state} onChange={event => setEditForm(current => ({ ...current, state: event.target.value }))}><option value="draft">Borrador / Pendiente</option><option value="progress">En Producción</option><option value="done">Finalizada</option></select></label>
              <label>Etapa actual<select className="input-control" value={editForm.current_stage} onChange={event => setEditForm(current => ({ ...current, current_stage: event.target.value }))}><option value="">Sin etapa</option>{DEFAULT_ZONES.map(zone => <option key={zone} value={zone}>{zone}</option>)}</select></label>
              <label>Notas<textarea className="input-control" rows={3} value={editForm.notes} onChange={event => setEditForm(current => ({ ...current, notes: event.target.value }))} /></label>
              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
                <button type="button" className="btn btn-outline" onClick={() => setEditingOrder(null)}>Cancelar</button>
                <button type="submit" className="btn btn-primary" disabled={editSubmitting}>{editSubmitting ? 'Guardando...' : 'Guardar cambios'}</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
