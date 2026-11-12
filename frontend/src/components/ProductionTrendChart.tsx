import React from 'react';
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { ProductionTrendPoint } from '../types';

interface ProductionTrendChartProps {
  points: ProductionTrendPoint[];
  rangeHours: number;
  intervalMinutes: number;
  endTimestamp: number;
}

const stageColors = ['#087e91', '#d97706', '#16a34a', '#dc5a52', '#7259a5'];

const stageLabels: Record<string, string> = {
  DOBLADO: 'Doblado',
  ARMADO_ESTRUCTURAL: 'Armado estructural',
  VINILADO: 'Vinilado',
  ALMACEN: 'Almacén',
  NO_IDENTIFICADO: 'No identificado',
};

const ProductionTrendChart: React.FC<ProductionTrendChartProps> = ({ points, rangeHours, intervalMinutes, endTimestamp }) => {
  const stageNames = Array.from(new Set(points.map((point) => point.stage))).sort();
  const bucketMilliseconds = intervalMinutes * 60_000;
  const firstBucket = Math.floor((endTimestamp - rangeHours * 60 * 60 * 1000) / bucketMilliseconds) * bucketMilliseconds;
  const currentBucket = Math.floor(endTimestamp / bucketMilliseconds) * bucketMilliseconds;
  const countsByBucket = new Map<number, Record<string, number>>();

  for (const point of points) {
    const bucket = Math.floor(new Date(point.timestamp).getTime() / bucketMilliseconds) * bucketMilliseconds;
    const counts = countsByBucket.get(bucket) ?? {};
    counts[point.stage] = point.count;
    countsByBucket.set(bucket, counts);
  }

  const chartData = [];
  for (let bucket = firstBucket; bucket <= currentBucket; bucket += bucketMilliseconds) {
    chartData.push({
      timestamp: bucket,
      ...Object.fromEntries(stageNames.map((stage) => [stage, countsByBucket.get(bucket)?.[stage] ?? 0])),
    });
  }

  const formatTime = (value: number) => new Date(value).toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
    ...(rangeHours === 24 ? { day: '2-digit', month: '2-digit' } : {}),
  });

  return (
    <ResponsiveContainer width="100%" height="100%">
      <LineChart data={chartData} margin={{ top: 8, right: 18, left: -18, bottom: 4 }}>
        <CartesianGrid stroke="#e5e9ec" strokeDasharray="3 5" vertical={false} />
        <XAxis
          dataKey="timestamp"
          tickFormatter={formatTime}
          tick={{ fill: '#64748b', fontSize: 11 }}
          tickLine={false}
          axisLine={false}
          minTickGap={32}
        />
        <YAxis allowDecimals={false} tick={{ fill: '#64748b', fontSize: 11 }} tickLine={false} axisLine={false} />
        <Tooltip
          labelFormatter={(value) => new Date(Number(value)).toLocaleString()}
          formatter={(value, name) => [value, stageLabels[String(name)] ?? String(name)]}
          contentStyle={{ borderRadius: 4, borderColor: '#d9e1e5', fontSize: 12 }}
        />
        <Legend formatter={(value) => stageLabels[value] ?? value} />
        {stageNames.map((stage, index) => (
          <Line
            key={stage}
            type="monotone"
            dataKey={stage}
            name={stage}
            stroke={stageColors[index % stageColors.length]}
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4 }}
            isAnimationActive={false}
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
};

export default ProductionTrendChart;