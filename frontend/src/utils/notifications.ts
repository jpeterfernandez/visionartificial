import Swal from 'sweetalert2';

const toast = Swal.mixin({
  toast: true,
  position: 'top-end',
  showConfirmButton: false,
  timer: 2500,
  timerProgressBar: true,
});

export const showSuccessToast = (message: string) =>
  toast.fire({ icon: 'success', title: message });

export const showErrorToast = (message: string) =>
  toast.fire({ icon: 'error', title: message });

export const confirmCameraDeletion = () =>
  Swal.fire({
    icon: 'warning',
    title: '¿Eliminar cámara?',
    text: 'Esta acción eliminará la cámara del sistema.',
    showCancelButton: true,
    confirmButtonText: 'Eliminar',
    cancelButtonText: 'Cancelar',
    confirmButtonColor: '#dc2626',
    reverseButtons: true,
  });

export const confirmUserDeletion = (count: number) =>
  Swal.fire({
    icon: 'warning',
    title: count === 1 ? '¿Eliminar usuario?' : `¿Eliminar ${count} usuarios?`,
    text: 'No podrán volver a iniciar sesión con estas cuentas.',
    showCancelButton: true,
    confirmButtonText: count === 1 ? 'Eliminar usuario' : `Eliminar ${count} usuarios`,
    cancelButtonText: 'Cancelar',
    confirmButtonColor: '#dc2626',
    reverseButtons: true,
  });

export const confirmProductionEventDeletion = (eventId: number) =>
  Swal.fire({
    icon: 'warning',
    title: `¿Eliminar el evento #${eventId}?`,
    text: 'Esta acción no se puede deshacer.',
    showCancelButton: true,
    confirmButtonText: 'Eliminar evento',
    cancelButtonText: 'Cancelar',
    confirmButtonColor: '#dc2626',
    reverseButtons: true,
  });

export const confirmProductionOrderDeletion = (orderName: string) =>
  Swal.fire({
    icon: 'warning',
    title: `¿Eliminar la orden ${orderName}?`,
    text: 'Se conservarán sus eventos de historial.',
    showCancelButton: true,
    confirmButtonText: 'Eliminar orden',
    cancelButtonText: 'Cancelar',
    confirmButtonColor: '#dc2626',
    reverseButtons: true,
  });