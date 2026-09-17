"""Identity tokens for authenticated Cloud Run-to-Cloud Run requests."""

from __future__ import annotations

import threading

from google.auth.compute_engine.credentials import IDTokenCredentials
from google.auth.transport.requests import Request

_credentials: dict[str, IDTokenCredentials] = {}
_lock = threading.Lock()


def fetch_id_token(audience: str) -> str:
    """Return a cached, valid ID token minted by the workload service account."""
    with _lock:
        credentials = _credentials.get(audience)
        if credentials is None:
            request = Request()
            credentials = IDTokenCredentials(  # type: ignore[no-untyped-call]
                request=request,
                target_audience=audience,
                use_metadata_identity_endpoint=True,
            )
            _credentials[audience] = credentials

        if not credentials.valid:
            credentials.refresh(Request())  # type: ignore[no-untyped-call]

        token = credentials.token
        if not isinstance(token, str) or not token:
            raise RuntimeError("Cloud Run metadata server returned an empty ID token")
        return token
