"""Process-wide transfer metrics for scrape cost estimation."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SourceTransferStats:
    requests: int = 0
    bytes_downloaded: int = 0
    bytes_uploaded: int = 0
    direct_requests: int = 0
    proxy_requests: int = 0
    restricted_hits: int = 0
    errors: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "requests": self.requests,
            "bytes_downloaded": self.bytes_downloaded,
            "bytes_uploaded": self.bytes_uploaded,
            "bytes_downloaded_mb": round(self.bytes_downloaded / (1024 * 1024), 3),
            "bytes_uploaded_mb": round(self.bytes_uploaded / (1024 * 1024), 3),
            "direct_requests": self.direct_requests,
            "proxy_requests": self.proxy_requests,
            "restricted_hits": self.restricted_hits,
            "errors": self.errors,
        }


@dataclass
class TransferMetrics:
    """Thread-safe counters: lifetime + current scrape session."""

    _lock: threading.Lock = field(default_factory=threading.Lock)
    lifetime: dict[str, SourceTransferStats] = field(default_factory=dict)
    session: dict[str, SourceTransferStats] = field(default_factory=dict)
    session_started_at: float | None = None
    session_label: str | None = None

    def start_session(self, label: str | None = None) -> None:
        with self._lock:
            self.session = {}
            self.session_started_at = time.time()
            self.session_label = label

    def end_session(self) -> dict[str, Any]:
        with self._lock:
            snap = self.snapshot_unlocked(include_session=True)
            self.session_started_at = None
            self.session_label = None
            return snap

    def record(
        self,
        source_id: str,
        *,
        bytes_down: int = 0,
        bytes_up: int = 0,
        transport: str = "direct",
        restricted: bool = False,
        error: bool = False,
    ) -> None:
        with self._lock:
            for bucket in (self.lifetime, self.session):
                st = bucket.setdefault(source_id, SourceTransferStats())
                st.requests += 1
                st.bytes_downloaded += max(0, int(bytes_down))
                st.bytes_uploaded += max(0, int(bytes_up))
                if transport == "proxy":
                    st.proxy_requests += 1
                else:
                    st.direct_requests += 1
                if restricted:
                    st.restricted_hits += 1
                if error:
                    st.errors += 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return self.snapshot_unlocked(include_session=True)

    def snapshot_unlocked(self, *, include_session: bool) -> dict[str, Any]:
        def pack(d: dict[str, SourceTransferStats]) -> dict[str, Any]:
            by_source = {k: v.to_dict() for k, v in sorted(d.items())}
            total = SourceTransferStats()
            for v in d.values():
                total.requests += v.requests
                total.bytes_downloaded += v.bytes_downloaded
                total.bytes_uploaded += v.bytes_uploaded
                total.direct_requests += v.direct_requests
                total.proxy_requests += v.proxy_requests
                total.restricted_hits += v.restricted_hits
                total.errors += v.errors
            return {"by_source": by_source, "total": total.to_dict()}

        out: dict[str, Any] = {
            "lifetime": pack(self.lifetime),
        }
        if include_session:
            out["session"] = pack(self.session)
            out["session_label"] = self.session_label
            out["session_started_at"] = self.session_started_at
        return out


_METRICS = TransferMetrics()


def get_transfer_metrics() -> TransferMetrics:
    return _METRICS
