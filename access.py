"""Owner-only access to the private workspace using managed Neon Auth."""
import os
import threading
from urllib.parse import urlparse

import jwt


class WorkspaceAccess:
    def __init__(self):
        self.base_url = os.getenv("NEON_AUTH_BASE_URL", "").rstrip("/")
        self.owner = os.getenv("BRIEFOPS_OWNER_EMAIL", "").strip().lower()
        self.client = None
        self.lock = threading.Lock()
        if self.base_url:
            self.client = jwt.PyJWKClient(
                os.getenv("NEON_AUTH_JWKS_URL") or self.base_url + "/.well-known/jwks.json",
                cache_jwk_set=True, lifespan=300, timeout=10,
            )

    @property
    def configured(self):
        return bool(self.client and self.owner)

    def authorized(self, authorization):
        if not self.configured or not authorization.startswith("Bearer "):
            return False
        token = authorization[7:]
        try:
            origin = urlparse(self.base_url)
            issuer = origin.scheme + "://" + origin.netloc
            with self.lock:
                key = self.client.get_signing_key_from_jwt(token)
            claims = jwt.decode(token, key.key, algorithms=["EdDSA"], issuer=issuer,
                                audience=issuer, options={"require": ["exp", "iat", "sub", "iss", "aud"]})
            return (claims.get("email", "").lower() == self.owner
                    and claims.get("emailVerified") is True
                    and claims.get("banned") is not True)
        except (jwt.PyJWTError, ValueError, OSError):
            return False
