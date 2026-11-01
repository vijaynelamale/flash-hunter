"""Resilient HTTP Transport Adapter for Flash-Hunter.

Primary: curl_cffi AsyncSession with browser impersonation (chrome124).
Fallback: httpx.AsyncClient with HTTP/2 and modern SSL cipher suite.
"""

import logging
import ssl
from dataclasses import dataclass
from typing import Dict, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Check curl_cffi availability
CURL_CFFI_AVAILABLE = False
try:
    from curl_cffi.requests import AsyncSession as CurlAsyncSession
    CURL_CFFI_AVAILABLE = True
except (ImportError, Exception) as e:
    logger.warning("curl_cffi unavailable (%s); falling back to httpx transport", e)

import httpx


@dataclass
class HttpResponse:
    status_code: int
    text: str
    url: str
    headers: Dict[str, str]


class ResilientHttpClient:
    """High-performance WAF-resilient HTTP client with automatic transport fallback."""

    def __init__(
        self,
        impersonate: str = "chrome124",
        timeout_seconds: float = 10.0,
        user_agent: Optional[str] = None,
    ):
        self.impersonate = impersonate
        self.timeout_seconds = timeout_seconds
        self.default_headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-IN,en-GB;q=0.9,en-US;q=0.8,en;q=0.7",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "User-Agent": user_agent
            or "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        }
        self._curl_session: Optional[Any] = None
        self._httpx_client: Optional[httpx.AsyncClient] = None

    def _create_ssl_context(self) -> ssl.SSLContext:
        """Constructs modern Chrome-like SSL context for httpx fallback."""
        ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
        ctx.set_ciphers(
            "ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:"
            "ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:"
            "ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:"
            "ECDHE-RSA-AES128-SHA:ECDHE-RSA-AES256-SHA:AES128-GCM-SHA256"
        )
        ctx.set_alpn_protocols(["h2", "http/1.1"])
        return ctx

    async def get(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        follow_redirects: bool = True,
        timeout: Optional[float] = None,
    ) -> HttpResponse:
        """Executes GET request with primary curl_cffi and fallback to httpx."""
        req_headers = {**self.default_headers, **(headers or {})}
        timeout_val = timeout or self.timeout_seconds

        if CURL_CFFI_AVAILABLE:
            try:
                if self._curl_session is None:
                    self._curl_session = CurlAsyncSession(impersonate=self.impersonate)
                
                resp = await self._curl_session.get(
                    url,
                    headers=req_headers,
                    allow_redirects=follow_redirects,
                    timeout=timeout_val,
                )
                return HttpResponse(
                    status_code=resp.status_code,
                    text=resp.text,
                    url=str(resp.url),
                    headers=dict(resp.headers),
                )
            except Exception as exc:
                logger.debug("curl_cffi fetch failed for %s (%s). Attempting httpx fallback.", url, exc)

        # Fallback to httpx with HTTP/2 and modern SSL
        if self._httpx_client is None:
            self._httpx_client = httpx.AsyncClient(
                http2=True,
                verify=self._create_ssl_context(),
                timeout=httpx.Timeout(timeout_val),
                headers=self.default_headers,
            )

        resp = await self._httpx_client.get(
            url,
            headers=req_headers,
            follow_redirects=follow_redirects,
        )
        return HttpResponse(
            status_code=resp.status_code,
            text=resp.text,
            url=str(resp.url),
            headers=dict(resp.headers),
        )

    async def unshorten_url(self, short_url: str, max_redirects: int = 5) -> str:
        """Resolves affiliate/shortened links to canonical landing URLs."""
        current_url = short_url
        for _ in range(max_redirects):
            try:
                resp = await self.get(current_url, follow_redirects=False, timeout=5.0)
                if resp.status_code in (301, 302, 303, 307, 308):
                    loc = resp.headers.get("location") or resp.headers.get("Location")
                    if loc:
                        if loc.startswith("http://") or loc.startswith("https://"):
                            current_url = loc
                        else:
                            parsed = urlparse(current_url)
                            current_url = f"{parsed.scheme}://{parsed.netloc}{loc}"
                        continue
                # If 200 or not a redirect, return current resolved URL
                return resp.url
            except Exception as e:
                logger.debug("Unshorten step failed for %s: %s", current_url, e)
                break
        return current_url

    async def close(self) -> None:
        """Closes all underlying sessions."""
        if self._curl_session is not None:
            try:
                await self._curl_session.close()
            except Exception:
                pass
            self._curl_session = None

        if self._httpx_client is not None:
            try:
                await self._httpx_client.aclose()
            except Exception:
                pass
            self._httpx_client = None
