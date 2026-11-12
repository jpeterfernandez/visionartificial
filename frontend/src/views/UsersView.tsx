import React, { useEffect, useState } from 'react';
import { Pencil, RefreshCw, Trash2, UserPlus, Users, X } from 'lucide-react';
import { createUserApi, deleteUserApi, getUsersApi, updateUserApi } from '../api/endpoints';
import type { User, UserRole } from '../types';
import { confirmUserDeletion, showErrorToast, showSuccessToast } from '../utils/notifications';
import { useAuth } from '../context/useAuth';

const PRODUCTION_ZONES = ['DOBLADO', 'ARMADO_ESTRUCTURAL', 'VINILADO', 'ALMACEN'];
const emptyForm = {
  username: '',
  full_name: '',
  role: 'OPERATOR' as UserRole,
  password: '',
  allowed_zones: [] as string[],
};

type UserChanges = { full_name?: string; role?: UserRole; allowed_zones?: string[]; is_active?: boolean; password?: string };
type UserEditForm = Required<Pick<UserChanges, 'full_name' | 'role' | 'allowed_zones' | 'is_active'>> & { password: string };

export const UsersView: React.FC = () => {
  const { user: currentUser } = useAuth();
  const [users, setUsers] = useState<User[]>([]);
  const [form, setForm] = useState(emptyForm);
  const [editForm, setEditForm] = useState<UserEditForm | null>(null);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [savingId, setSavingId] = useState<number | null>(null);
  const [selectedUserIds, setSelectedUserIds] = useState<Set<number>>(new Set());
  const [deletingUsers, setDeletingUsers] = useState(false);

  const loadUsers = async () => {
    try {
      setUsers(await getUsersApi());
    } catch (error) {
      showErrorToast(error instanceof Error ? error.message : 'No se pudieron cargar los usuarios');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    let active = true;
    getUsersApi()
      .then(data => {
        if (!active) return;
        setUsers(data);
      })
      .catch(error => {
        if (active) showErrorToast(error instanceof Error ? error.message : 'No se pudieron cargar los usuarios');
      })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  const handleCreate = async (event: React.FormEvent) => {
    event.preventDefault();
    setSubmitting(true);
    try {
      await createUserApi({
        ...form,
        allowed_zones: form.role === 'ADMIN' ? [] : form.allowed_zones,
        is_active: true,
      });
      setForm(emptyForm);
      await loadUsers();
      setShowCreateModal(false);
      showSuccessToast('Usuario creado.');
    } catch (error) {
      showErrorToast(error instanceof Error ? error.message : 'No se pudo crear el usuario');
    } finally {
      setSubmitting(false);
    }
  };

  const handleUpdateUser = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!editingUser || !editForm) return;
    setSavingId(editingUser.id);
    try {
      const { password, ...changes } = editForm;
      const normalizedChanges = { ...changes, allowed_zones: changes.role === 'ADMIN' ? [] : changes.allowed_zones };
      const updated = await updateUserApi(editingUser.id, password ? { ...normalizedChanges, password } : normalizedChanges);
      setUsers(current => current.map(item => item.id === editingUser.id ? updated : item));
      setEditForm(null);
      setEditingUser(null);
      showSuccessToast(password ? 'Usuario y contraseña actualizados.' : 'Usuario actualizado.');
    } catch (error) {
      showErrorToast(error instanceof Error ? error.message : 'No se pudo actualizar el usuario');
      await loadUsers();
    } finally {
      setSavingId(null);
    }
  };

  const [editingUser, setEditingUser] = useState<User | null>(null);

  const toggleZone = (zone: string, checked: boolean) => {
    setForm(current => ({
      ...current,
      allowed_zones: checked
        ? [...new Set([...current.allowed_zones, zone])]
        : current.allowed_zones.filter(value => value !== zone),
    }));
  };

  const toggleEditZone = (zone: string, checked: boolean) => {
    setEditForm(current => current ? ({
      ...current,
      allowed_zones: checked
        ? [...new Set([...current.allowed_zones, zone])]
        : current.allowed_zones.filter(value => value !== zone),
    }) : current);
  };

  const openEditModal = (item: User) => {
    setEditingUser(item);
    setEditForm({
      full_name: item.full_name,
      role: item.role,
      allowed_zones: (item.allowed_zones || []).filter(zone => PRODUCTION_ZONES.includes(zone)),
      is_active: item.is_active,
      password: '',
    });
  };

  const selectableUsers = users.filter(item => item.id !== currentUser?.id);
  const allUsersSelected = selectableUsers.length > 0 && selectableUsers.every(item => selectedUserIds.has(item.id));

  const toggleUserSelection = (userId: number, checked: boolean) => {
    setSelectedUserIds(current => {
      const next = new Set(current);
      if (checked) next.add(userId);
      else next.delete(userId);
      return next;
    });
  };

  const toggleAllUsers = (checked: boolean) => {
    setSelectedUserIds(checked ? new Set(selectableUsers.map(item => item.id)) : new Set());
  };

  const handleDeleteSelected = async () => {
    const ids = [...selectedUserIds];
    if (!ids.length) return;
    const confirmation = await confirmUserDeletion(ids.length);
    if (!confirmation.isConfirmed) return;

    setDeletingUsers(true);
    const results = await Promise.allSettled(ids.map(id => deleteUserApi(id)));
    const deletedIds = new Set(ids.filter((_, index) => results[index].status === 'fulfilled'));
    setUsers(current => current.filter(item => !deletedIds.has(item.id)));
    setSelectedUserIds(new Set());
    setDeletingUsers(false);

    const failedCount = results.length - deletedIds.size;
    if (failedCount) {
      showErrorToast(`Se eliminaron ${deletedIds.size}; ${failedCount} no se pudieron eliminar.`);
      await loadUsers();
    } else {
      showSuccessToast(deletedIds.size === 1 ? 'Usuario eliminado.' : `${deletedIds.size} usuarios eliminados.`);
    }
  };

  if (currentUser?.role !== 'ADMIN') {
    return <div className="view-container"><h2>Acceso restringido</h2></div>;
  }

  return (
    <div className="view-container">
      <div className="view-header">
        <div>
          <h2 style={{ fontSize: '1.25rem', fontWeight: 700, color: '#0f172a' }}>Administración de usuarios</h2>
          <p style={{ fontSize: '0.85rem', color: '#64748b' }}>Roles y zonas permitidas</p>
        </div>
        <div className="users-header-actions">
          <button onClick={() => { setLoading(true); void loadUsers(); }} disabled={loading} className="btn btn-outline btn-sm">
            <RefreshCw size={14} /> Actualizar
          </button>
          <button onClick={() => setShowCreateModal(true)} className="btn btn-primary btn-sm">
            <UserPlus size={14} /> Nuevo usuario
          </button>
        </div>
      </div>

      <section className="card">
        <div className="card-header"><h3 className="card-title"><Users size={17} /> Usuarios registrados</h3><span>{users.length}</span></div>
        {selectedUserIds.size > 0 && (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, padding: '10px 14px', borderBottom: '1px solid #e2e8f0' }}>
            <span>{selectedUserIds.size} seleccionados</span>
            <button type="button" className="btn btn-outline btn-sm" onClick={handleDeleteSelected} disabled={deletingUsers} style={{ color: '#dc2626' }}>
              {deletingUsers ? <RefreshCw className="animate-spin" size={14} /> : <Trash2 size={14} />}
              {deletingUsers ? 'Eliminando...' : 'Eliminar seleccionados'}
            </button>
          </div>
        )}
        {loading ? <p>Cargando usuarios...</p> : users.length === 0 ? <p>No hay usuarios registrados.</p> : (
          <div className="table-responsive">
            <table className="users-table">
              <thead><tr><th><input type="checkbox" aria-label="Seleccionar todos los usuarios disponibles" checked={allUsersSelected} onChange={event => toggleAllUsers(event.target.checked)} /></th><th>Usuario</th><th>Rol</th><th>Zonas permitidas</th><th>Acceso</th><th>Creado</th><th>Acciones</th></tr></thead>
              <tbody>{users.map(item => (
                <tr key={item.id}>
                  <td><input type="checkbox" aria-label={`Seleccionar a ${item.username}`} checked={selectedUserIds.has(item.id)} disabled={item.id === currentUser?.id || deletingUsers} onChange={event => toggleUserSelection(item.id, event.target.checked)} /></td>
                  <td><strong>{item.full_name}</strong><small className="users-username">{item.username}</small></td>
                  <td><span className="users-role">{item.role}</span></td>
                  <td>{item.role === 'ADMIN' ? 'Todas las zonas' : (item.allowed_zones || []).join(', ') || 'Sin zonas'}</td>
                  <td><span className={`users-status ${item.is_active ? 'is-active' : ''}`}>{item.is_active ? 'Activo' : 'Desactivado'}</span></td>
                  <td>{new Date(item.created_at).toLocaleDateString()}</td>
                  <td>
                    <div style={{ display: 'flex', gap: '6px' }}>
                      <button type="button" className="btn btn-outline btn-sm" disabled={savingId === item.id || deletingUsers} onClick={() => openEditModal(item)}>
                        <Pencil size={13} /> Editar
                      </button>
                      <button
                        type="button"
                        className="btn btn-outline btn-sm"
                        disabled={item.id === currentUser?.id || deletingUsers}
                        onClick={async () => {
                          const confirmation = await confirmUserDeletion(1);
                          if (!confirmation.isConfirmed) return;
                          setDeletingUsers(true);
                          try {
                            await deleteUserApi(item.id);
                            setUsers(current => current.filter(u => u.id !== item.id));
                            setSelectedUserIds(current => {
                              const next = new Set(current);
                              next.delete(item.id);
                              return next;
                            });
                            showSuccessToast('Usuario eliminado.');
                          } catch (error) {
                            showErrorToast(error instanceof Error ? error.message : 'No se pudo eliminar el usuario');
                          } finally {
                            setDeletingUsers(false);
                          }
                        }}
                        style={{ color: '#dc2626', borderColor: '#fca5a5' }}
                        title={item.id === currentUser?.id ? 'No puedes eliminar tu propia cuenta' : 'Eliminar usuario'}
                      >
                        <Trash2 size={13} /> Eliminar
                      </button>
                    </div>
                  </td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        )}
      </section>

      {showCreateModal && (
        <div className="modal-overlay" onClick={() => setShowCreateModal(false)}>
          <div className="modal-content users-modal" role="dialog" aria-modal="true" aria-labelledby="create-user-title" onClick={event => event.stopPropagation()}>
            <div className="users-modal-header">
              <div><h3 id="create-user-title">Nuevo usuario</h3><p>Configura sus datos de acceso y permisos.</p></div>
              <button type="button" className="btn btn-outline btn-sm" aria-label="Cerrar" onClick={() => setShowCreateModal(false)}><X size={16} /></button>
            </div>
            <form onSubmit={handleCreate} className="users-modal-form">
              <label>Usuario<input className="input-control" required minLength={3} maxLength={50} autoComplete="username" value={form.username} onChange={event => setForm(current => ({ ...current, username: event.target.value }))} /></label>
              <label>Nombre completo<input className="input-control" required minLength={2} maxLength={100} value={form.full_name} onChange={event => setForm(current => ({ ...current, full_name: event.target.value }))} /></label>
              <label>Rol<select className="input-control" value={form.role} onChange={event => setForm(current => ({ ...current, role: event.target.value as UserRole }))}><option value="OPERATOR">Operador</option><option value="VIEWER">Consulta</option><option value="ADMIN">Administrador</option></select></label>
              <label>Contraseña inicial<input className="input-control" type="password" required minLength={12} maxLength={128} autoComplete="new-password" value={form.password} onChange={event => setForm(current => ({ ...current, password: event.target.value }))} /></label>
              {form.role !== 'ADMIN' && (
                <fieldset className="users-zone-picker">
                  <legend>Zonas autorizadas</legend>
                  <div>{PRODUCTION_ZONES.map(zone => <label key={zone}><input type="checkbox" checked={form.allowed_zones.includes(zone)} onChange={event => toggleZone(zone, event.target.checked)} /> {zone}</label>)}</div>
                </fieldset>
              )}
              <div className="users-modal-actions">
                <button type="button" className="btn btn-outline" onClick={() => setShowCreateModal(false)}>Cancelar</button>
                <button className="btn btn-primary" type="submit" disabled={submitting || (form.role !== 'ADMIN' && form.allowed_zones.length === 0)}>
                  {submitting ? <RefreshCw className="animate-spin" size={15} /> : <UserPlus size={15} />} Crear usuario
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {editingUser && editForm && (
        <div className="modal-overlay" onClick={() => { setEditingUser(null); setEditForm(null); }}>
          <div className="modal-content users-modal" role="dialog" aria-modal="true" aria-labelledby="edit-user-title" onClick={event => event.stopPropagation()}>
            <div className="users-modal-header">
              <div><h3 id="edit-user-title">Editar usuario</h3><p>{editingUser.username}</p></div>
              <button type="button" className="btn btn-outline btn-sm" aria-label="Cerrar" onClick={() => { setEditingUser(null); setEditForm(null); }}><X size={16} /></button>
            </div>
            <form onSubmit={handleUpdateUser} className="users-modal-form">
              <label>Nombre completo<input className="input-control" required minLength={2} maxLength={100} value={editForm.full_name} onChange={event => setEditForm(current => current ? { ...current, full_name: event.target.value } : current)} /></label>
              <label>Rol<select className="input-control" value={editForm.role} onChange={event => setEditForm(current => current ? { ...current, role: event.target.value as UserRole } : current)}><option value="OPERATOR">Operador</option><option value="VIEWER">Consulta</option><option value="ADMIN">Administrador</option></select></label>
              {editForm.role !== 'ADMIN' && (
                <fieldset className="users-zone-picker">
                  <legend>Zonas autorizadas</legend>
                  <div>{PRODUCTION_ZONES.map(zone => <label key={zone}><input type="checkbox" checked={editForm.allowed_zones.includes(zone)} onChange={event => toggleEditZone(zone, event.target.checked)} /> {zone}</label>)}</div>
                </fieldset>
              )}
              <label className="users-active-toggle"><input type="checkbox" checked={editForm.is_active} disabled={editingUser.id === currentUser.id} onChange={event => setEditForm(current => current ? { ...current, is_active: event.target.checked } : current)} /> Cuenta activa{editingUser.id === currentUser.id && <small>No puedes desactivar tu propia cuenta.</small>}</label>
              <label className="users-password-field">Nueva contraseña <small>Déjala vacía para conservar la actual.</small><input className="input-control" type="password" minLength={12} maxLength={128} autoComplete="new-password" value={editForm.password} onChange={event => setEditForm(current => current ? { ...current, password: event.target.value } : current)} /></label>
              <div className="users-modal-actions">
                <button type="button" className="btn btn-outline" onClick={() => { setEditingUser(null); setEditForm(null); }}>Cancelar</button>
                <button className="btn btn-primary" type="submit" disabled={savingId === editingUser.id || editForm.full_name.trim().length < 2 || (editForm.role !== 'ADMIN' && editForm.allowed_zones.length === 0) || (editForm.password.length > 0 && editForm.password.length < 12)}>
                  {savingId === editingUser.id ? <RefreshCw className="animate-spin" size={15} /> : <Pencil size={15} />} Guardar cambios
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
