"""Owner-only access to the private workspace using managed Neon Auth."""
import os
import threading
import time
from urllib.parse import urlparse

import jwt


class WorkspaceAccess:
    def __init__(self):
        self.base_url = os.getenv("NEON_AUTH_BASE_URL", "").rstrip("/")
        self.owner = os.getenv("BRIEFOPS_OWNER_EMAIL", "").strip().lower()
        self.client = None
        self.lock = threading.Lock()
        self.keys = []
        self.expires = 0
        self.refreshed = 0
        self.failed_until = 0
        if self.base_url:
            self.client = jwt.PyJWKClient(
                os.getenv("NEON_AUTH_JWKS_URL") or self.base_url + "/.well-known/jwks.json",
                cache_jwk_set=True, lifespan=300, timeout=10,
            )

    @property
    def configured(self):
        return bool(self.client and self.owner)

    def authorized(self, authorization):
        if not self.configured or not authorization.startswith("Bearer ") or len(authorization) > 8200:
            return False
        token = authorization[7:]
        try:
            header = jwt.get_unverified_header(token)
            kid = header.get("kid")
            if header.get("alg") != "EdDSA" or not isinstance(kid, str) or not 1 <= len(kid) <= 128:
                return False
            origin = urlparse(self.base_url)
            issuer = origin.scheme + "://" + origin.netloc
            with self.lock:
                now = time.monotonic()
                if now < self.failed_until:
                    return False
                try:
                    if not self.keys or now >= self.expires:
                        self.keys = self.client.get_signing_keys(refresh=True)
                        self.expires, self.refreshed = now + 300, now
                    key = next((item for item in self.keys if item.key_id == kid), None)
                    # Unknown key IDs cannot force a remote request on every attempt.
                    if not key and now - self.refreshed >= 30:
                        self.keys = self.client.get_signing_keys(refresh=True)
                        self.expires, self.refreshed = now + 300, now
                        key = next((item for item in self.keys if item.key_id == kid), None)
                except (jwt.PyJWTError, OSError):
                    self.failed_until = now + 5
                    return False
                if key is None:
                    return False
            claims = jwt.decode(token, key.key, algorithms=["EdDSA"], issuer=issuer,
                                audience=issuer, options={"require": ["exp", "iat", "sub", "iss", "aud"]})
            return (isinstance(claims.get("email"), str) and claims["email"].lower() == self.owner
                    and claims.get("emailVerified") is True
                    and claims.get("banned") is not True)
        except (jwt.PyJWTError, ValueError, OSError):
            return False
