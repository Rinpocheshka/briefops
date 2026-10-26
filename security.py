"""Bound resource usage at the HTTP boundary; proxy identity is deployment-specific."""
import ipaddress
import os
import threading
import time
from collections import OrderedDict, deque
from http.server import ThreadingHTTPServer


def remote_address(headers, peer):
    # Render documents a sanitized client IP first in XFF. Direct/local requests
    # never get to choose an identity by providing their own forwarded header.
    value = headers.get("X-Forwarded-For", "").split(",")[0].strip() if os.getenv("RENDER") else peer
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return peer


class RequestLimiter:
    def __init__(self, max_keys=2048):
        self.entries = OrderedDict()
        self.lock = threading.Lock()
        self.max_keys = max_keys

    def allow(self, key, limit, period=60):
        now = time.monotonic()
        with self.lock:
            recent = self.entries.pop(key, deque())
            while recent and recent[0] <= now - period:
                recent.popleft()
            allowed = len(recent) < limit
            if allowed:
                recent.append(now)
            self.entries[key] = recent
            while len(self.entries) > self.max_keys:
                self.entries.popitem(last=False)
            return allowed


class BoundedHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 64

    def __init__(self, *args, **kwargs):
        self.slots = threading.BoundedSemaphore(32)
        super().__init__(*args, **kwargs)

    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            try:
                request.settimeout(2)
                request.sendall(b"HTTP/1.0 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.slots.release()
