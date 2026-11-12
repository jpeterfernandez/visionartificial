import React, { useState, useEffect, useCallback } from 'react';
import { getModelStatusApi, detectImageApi, exportDetectionsCsvApi, getCamerasApi } from '../api/endpoints';
import type { ModelStatus, DetectionImageResponse, Camera } from '../types';
import { Upload, Crosshair, AlertCircle, Download, RefreshCw } from 'lucide-react';
import { useAuth } from '../context/useAuth';

export const VisionView: React.FC = () => {
  const { user } = useAuth();
  const [modelStatus, setModelStatus] = useState<ModelStatus | null>(null);
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [selectedCameraId, setSelectedCameraId] = useState<number | undefined>(undefined);
  const [confThreshold, setConfThreshold] = useState<number>(0.60);
  const [showConfidence, setShowConfidence] = useState(true);
  
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [inferring, setInferring] = useState<boolean>(false);
  const [result, setResult] = useState<DetectionImageResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);

  const loadModelInfo = useCallback(async () => {
    try {
      const [status, cams] = await Promise.all([
        getModelStatusApi(),
        getCamerasApi()
      ]);
      setModelStatus(status);
      setCameras(cams);
      setSelectedCameraId(current => current ?? cams[0]?.id);
    } catch (err: any) {
      setError(err.message || 'Error consultando información del modelo');
    }
  }, []);

  useEffect(() => {
    void Promise.resolve().then(loadModelInfo);
  }, [loadModelInfo]);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      const file = e.target.files[0];
      setSelectedFile(file);
      setPreviewUrl(URL.createObjectURL(file));
      setResult(null);
      setError(null);
    }
  };

  const handleExecuteInference = async () => {
    if (!selectedFile) return;
    setInferring(true);
    setError(null);

    try {
      const data = await detectImageApi(selectedFile, selectedCameraId, confThreshold, showConfidence);
      setResult(data);
    } catch (err: any) {
      setError(err.message || 'Error durante la inferencia');
    } finally {
      setInferring(false);
    }
  };

  const handleExportDetections = async () => {
    setExporting(true);
    try {
      const blob = await exportDetectionsCsvApi({ camera_id: selectedCameraId });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = 'detecciones.csv';
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (exportError) {
      setError(exportError instanceof Error ? exportError.message : 'No se pudieron exportar las detecciones');
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className="view-container">
      <div className="view-header">
        <div>
            <h2 style={{ fontSize: '1.25rem', fontWeight: 700, color: '#0f172a' }}>Análisis de visión artificial</h2>
          <p style={{ fontSize: '0.85rem', color: '#64748b' }}>
            Procesamiento de imágenes y detección de etapas de producción.
          </p>
        </div>
        <button onClick={loadModelInfo} className="btn btn-outline btn-sm">
          <RefreshCw size={14} /> Recargar Modelo
        </button>
      </div>

      {/* Model Technical Card */}
      {modelStatus && (
        <div className="card" style={{ backgroundColor: '#f8fafc' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span className={`badge ${modelStatus.loaded ? 'badge-success' : 'badge-danger'}`}>
                {modelStatus.loaded ? 'best.pt cargado' : 'Modelo no cargado'}
              </span>
              <span style={{ fontSize: '0.8rem', color: '#64748b' }}>
                Dispositivo: <strong>{modelStatus.device.toUpperCase()}</strong> | Tamaño: {modelStatus.img_size}px
              </span>
            </div>
            <span style={{ fontSize: '0.75rem', color: '#94a3b8' }}>
              Ruta: {modelStatus.model_path}
            </span>
          </div>

          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', alignItems: 'center' }}>
            <span style={{ fontSize: '0.8rem', fontWeight: 600, color: '#475569' }}>Clases entrenadas reales:</span>
            {Object.entries(modelStatus.classes).map(([id, name]) => (
              <span key={id} style={{
                backgroundColor: '#ffffff',
                border: '1px solid #cbd5e1',
                padding: '2px 8px',
                borderRadius: '4px',
                fontSize: '0.75rem',
                fontFamily: 'monospace'
              }}>
                #{id}: <strong>{name}</strong>
              </span>
            ))}
          </div>
        </div>
      )}

      {error && (
        <div style={{
          backgroundColor: '#fee2e2',
          color: '#b91c1c',
          padding: '12px 16px',
          borderRadius: '6px',
          marginBottom: '20px',
          display: 'flex',
          alignItems: 'center',
          gap: '10px'
        }}>
          <AlertCircle size={18} />
          <span>{error}</span>
        </div>
      )}

      {/* Inference Testing Panel */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(380px, 1fr))', gap: '24px' }}>
        {/* Upload & Controls */}
        <div className="card">
          <div className="card-header">
            <h3 className="card-title">Procesar imagen</h3>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            <div>
              <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, marginBottom: '6px' }}>
                Asociar a una cámara (opcional)
              </label>
              <select
                className="input-control"
                value={selectedCameraId || ''}
                onChange={(e) => setSelectedCameraId(e.target.value ? Number(e.target.value) : undefined)}
              >
                <option value="">Sin asociar a una cámara</option>
                {cameras.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name} - Zona {c.zone}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, marginBottom: '6px' }}>
                Umbral de Confianza: {(confThreshold * 100).toFixed(0)}%
              </label>
              <input
                type="range"
                min="0.10"
                max="0.95"
                step="0.05"
                value={confThreshold}
                onChange={(e) => setConfThreshold(parseFloat(e.target.value))}
                style={{ width: '100%' }}
              />
            </div>

            <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.8rem', color: '#475569' }}>
              <input
                type="checkbox"
                checked={showConfidence}
                onChange={(e) => setShowConfidence(e.target.checked)}
              />
              Mostrar porcentaje en las etiquetas
            </label>

            <div style={{
              border: '2px dashed #cbd5e1',
              borderRadius: '8px',
              padding: '28px',
              textAlign: 'center',
              cursor: 'pointer',
              backgroundColor: '#fafbfc'
            }}
            onClick={() => { if (user?.role !== 'VIEWER') document.getElementById('image-upload-input')?.click(); }}
            >
              <Upload size={32} style={{ color: 'var(--primary)', margin: '0 auto 10px' }} />
              <p style={{ fontWeight: 600, fontSize: '0.9rem' }}>
                {selectedFile ? selectedFile.name : 'Haz clic para seleccionar una imagen'}
              </p>
              <p style={{ fontSize: '0.75rem', color: '#64748b', marginTop: '4px' }}>
                Formatos soportados: JPG, PNG, WEBP (máx. 15MB)
              </p>
              <input
                id="image-upload-input"
                type="file"
                accept="image/*"
                disabled={user?.role === 'VIEWER'}
                style={{ display: 'none' }}
                onChange={handleFileChange}
              />
            </div>

            <button
              onClick={handleExecuteInference}
              disabled={!selectedFile || inferring || user?.role === 'VIEWER'}
              className="btn btn-primary"
              style={{ width: '100%', height: '42px' }}
            >
              <Crosshair size={16} style={{ display: inferring ? 'none' : undefined }} />
              <RefreshCw
                className={inferring ? 'animate-spin' : undefined}
                size={16}
                style={{ display: inferring ? undefined : 'none' }}
              />
              {inferring ? 'Ejecutando inferencia YOLO26m...' : 'Analizar imagen'}
            </button>
            {user?.role !== 'VIEWER' && <button onClick={() => void handleExportDetections()} disabled={exporting} className="btn btn-outline" style={{ width: '100%', marginTop: 8 }}>
              <Download size={16} style={{ display: exporting ? 'none' : undefined }} />
              <RefreshCw
                className={exporting ? 'animate-spin' : undefined}
                size={16}
                style={{ display: exporting ? undefined : 'none' }}
              />
              Exportar detecciones CSV
            </button>}
          </div>
        </div>

        {/* Results Panel */}
        <div className="card">
          <div className="card-header">
            <h3 className="card-title">Resultado de Detección</h3>
            {result && (
              <span className="badge badge-success">
                {result.total_detections} objeto(s) detectados
              </span>
            )}
          </div>

          {!result && !previewUrl && (
            <div style={{ textAlign: 'center', padding: '60px 20px', color: '#94a3b8' }}>
              Selecciona una imagen para consultar el resultado del procesamiento y las clases detectadas.
            </div>
          )}

          {/* Image display */}
          {(result?.annotated_image_base64 || previewUrl) && (
            <div style={{ marginBottom: '16px', textAlign: 'center' }}>
              <img
                src={
                  result?.annotated_image_base64
                    ? `data:image/jpeg;base64,${result.annotated_image_base64}`
                    : previewUrl!
                }
                alt="Vista de análisis"
                style={{
                  maxWidth: '100%',
                  maxHeight: '360px',
                  borderRadius: '6px',
                  border: '1px solid #e2e8f0',
                  objectFit: 'contain'
                }}
              />
            </div>
          )}

          {/* Detections metadata */}
          {result && (
            <div>
              <div style={{
                display: 'flex',
                gap: '16px',
                padding: '10px 14px',
                backgroundColor: '#f1f5f9',
                borderRadius: '6px',
                marginBottom: '16px',
                fontSize: '0.8rem'
              }}>
                <div>Tiempo de Inferencia: <strong>{result.inference_time_ms} ms</strong></div>
                <div>Resolución: <strong>{result.image_width} x {result.image_height}</strong></div>
                {result.confirmed_event_id && (
                  <div style={{ color: '#16a34a' }}>
                    <strong>Evento #{result.confirmed_event_id} registrado en BD</strong>
                  </div>
                )}
              </div>

              {result.classifications.length > 0 && (
                <div style={{ marginBottom: '16px', padding: '12px 14px', border: '1px solid #bfdbfe', borderRadius: '8px', background: '#eff6ff' }}>
                  <strong style={{ display: 'block', marginBottom: '8px', color: '#1e3a8a', fontSize: '0.84rem' }}>Máquinas clasificadas</strong>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                    {result.classifications.map((classification, index) => (
                      <div key={`${classification.anchor_class}-${index}`} style={{ background: '#fff', border: '1px solid #dbeafe', borderRadius: '6px', padding: '7px 10px', fontSize: '0.78rem' }}>
                        <strong>{classification.label}</strong>
                        <span style={{ display: 'block', color: '#64748b', marginTop: '3px' }}>
                          {classification.classes.join(' · ')}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {result.detections.length === 0 ? (
                <div style={{ color: '#64748b', fontSize: '0.85rem' }}>
                  No se detectaron objetos que superen el umbral de confianza {(confThreshold * 100).toFixed(0)}%.
                </div>
              ) : (
                <div className="table-responsive">
                  <table>
                    <thead>
                      <tr>
                        <th>Clase Detectada</th>
                        <th>Etapa Asignada</th>
                        <th>Confianza</th>
                        <th>Bounding Box [X1, Y1, X2, Y2]</th>
                      </tr>
                    </thead>
                    <tbody>
                      {result.detections.map((d, idx) => (
                        <tr key={idx}>
                          <td><strong>{d.class_name}</strong></td>
                          <td>
                            <span className="badge badge-info">{d.stage_name || 'NO_IDENTIFICADO'}</span>
                          </td>
                          <td>{(d.confidence * 100).toFixed(1)}%</td>
                          <td style={{ fontFamily: 'monospace', fontSize: '0.8rem' }}>
                            [{d.bbox.x1}, {d.bbox.y1}, {d.bbox.x2}, {d.bbox.y2}]
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
