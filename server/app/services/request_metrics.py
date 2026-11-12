import threading
from collections import deque
from datetime import datetime, timezone
from typing import Dict, List


class RequestMetrics:
    def __init__(self, sample_limit: int = 1000):
        self._samples = deque(maxlen=sample_limit)
        self._lock = threading.Lock()

    def record(self, path: str, status_code: int, duration_ms: float) -> None:
        with self._lock:
            self._samples.append({
                "path": path,
                "status_code": status_code,
                "duration_ms": duration_ms,
                "recorded_at": datetime.now(timezone.utc).isoformat(),
            })

    def snapshot(self) -> Dict[str, object]:
        with self._lock:
            samples: List[dict] = list(self._samples)
        durations = sorted(sample["duration_ms"] for sample in samples)
        errors = sum(sample["status_code"] >= 500 for sample in samples)
        p95_index = max(0, int(len(durations) * 0.95) - 1)
        return {
            "sample_count": len(samples),
            "error_count": errors,
            "error_rate_percent": round(errors / len(samples) * 100, 2) if samples else 0,
            "average_latency_ms": round(sum(durations) / len(durations), 2) if durations else 0,
            "p95_latency_ms": round(durations[p95_index], 2) if durations else 0,
            "captured_at": datetime.now(timezone.utc).isoformat(),
        }


request_metrics = RequestMetrics()
