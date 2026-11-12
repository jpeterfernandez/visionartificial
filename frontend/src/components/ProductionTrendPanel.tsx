import React, { lazy, Suspense, useEffect, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { getDashboardProductionTrendsApi } from '../api/endpoints';
import type { ProductionTrendPoint } from '../types';

const ProductionTrendChart = lazy(() => import('./ProductionTrendChart'));

type TimeRange = 1 | 6 | 24;
type BucketSize = 1 | 5 | 15 | 60;

export const ProductionTrendPanel: React.FC = () => {
  const [rangeHours, setRangeHours] = useState<TimeRange>(6);
  const [intervalMinutes, setIntervalMinutes] = useState<BucketSize>(1);
  const [points, setPoints] = useState<ProductionTrendPoint[]>([]);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    const refresh = async () => {
      const end = new Date();
      const start = new Date(end.getTime() - rangeHours * 60 * 60 * 1000);
      try {
        setError(null);
        const data = await getDashboardProductionTrendsApi(
          start.toISOString(),
          end.toISOString(),
          intervalMinutes
        );
        if (active) {
          setPoints(data);
          setLastUpdated(new Date());
        }
      } catch (err: unknown) {
        if (active) {
          setError(err instanceof Error ? err.message : 'Error cargando la tendencia de producción');
        }
      } finally {
        if (active) setLoading(false);
      }
    };

    void refresh();
    const timer = window.setInterval(refresh, 60_000);

    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [rangeHours, intervalMinutes]);

  const totalRecords = points.reduce((total, point) => total + point.count, 0);

  return (
    <section className="card production-trend-panel">
      <div className="card-header production-trend-header">
        <div>
          <h3 className="card-title">Registros de detección por etapa</h3>
          <p className="production-trend-caption">Cada punto representa eventos registrados, no máquinas únicas.</p>
        </div>
        <div className="production-trend-controls">
          <label>
            <span>Periodo</span>
            <select className="input-control" value={rangeHours} onChange={(event) => {
              setLoading(true);
              setRangeHours(Number(event.target.value) as TimeRange);
            }}>
              <option value={1}>Última hora</option>
              <option value={6}>Últimas 6 horas</option>
              <option value={24}>Últimas 24 horas</option>
            </select>
          </label>
          <label>
            <span>Agrupar cada</span>
            <select className="input-control" value={intervalMinutes} onChange={(event) => {
              setLoading(true);
              setIntervalMinutes(Number(event.target.value) as BucketSize);
            }}>
              <option value={1}>1 minuto</option>
              <option value={5}>5 minutos</option>
              <option value={15}>15 minutos</option>
              <option value={60}>1 hora</option>
            </select>
          </label>
        </div>
      </div>

      <div className="production-trend-summary">
        <div>
          <span className="stat-label">Registros en el periodo</span>
          <strong>{totalRecords}</strong>
        </div>
        <span className="production-trend-updated">
          <RefreshCw size={14} className={loading ? 'animate-spin' : undefined} />
          {lastUpdated ? `Actualizado ${lastUpdated.toLocaleTimeString()}` : 'Esperando datos'}
        </span>
      </div>

      {error ? (
        <div className="production-trend-empty" role="alert">{error}</div>
      ) : loading && points.length === 0 ? (
        <div className="production-trend-empty">Cargando registros de producción...</div>
      ) : points.length === 0 ? (
        <div className="production-trend-empty">No hay eventos registrados en el periodo seleccionado.</div>
      ) : (
        <div className="production-trend-chart" aria-label="Gráfico temporal de eventos por etapa">
          <Suspense fallback={<div className="production-trend-empty">Preparando gráfico...</div>}>
            <ProductionTrendChart
              points={points}
              rangeHours={rangeHours}
              intervalMinutes={intervalMinutes}
              endTimestamp={lastUpdated?.getTime() ?? 0}
            />
          </Suspense>
        </div>
      )}
      <p className="production-trend-footnote">Actualización automática cada minuto.</p>
    </section>
  );
};