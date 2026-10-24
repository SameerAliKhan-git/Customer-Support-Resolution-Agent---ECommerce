"""OIDC access-token verification with pinned issuer, audience and asymmetric algorithms."""
import asyncio
from functools import lru_cache
from urllib.parse import urlparse
import time
import httpx
import jwt
from app.config import settings

@lru_cache(maxsize=4)
def key_client(issuer, jwks_uri):
    return jwt.PyJWKClient(jwks_uri, cache_jwk_set=True, lifespan=300, timeout=5)

_discovery_cache: dict = {}
_discovery_lock = asyncio.Lock()
DISCOVERY_TTL_SECONDS = 3600

def clear_discovery_cache():
    """Clear discovery document cache and JWK key client cache."""
    _discovery_cache.clear()
    key_client.cache_clear()

async def get_oidc_discovery(issuer: str) -> dict:
    """Fetch and cache the OpenID Connect discovery document."""
    now = time.monotonic()
    cached = _discovery_cache.get(issuer)
    if cached and now < cached[0]:
        return cached[1]
    async with _discovery_lock:
        cached = _discovery_cache.get(issuer)
        if cached and now < cached[0]:
            return cached[1]
        async with httpx.AsyncClient(timeout=5, follow_redirects=False) as client:
            response = await client.get(issuer + '/.well-known/openid-configuration')
            response.raise_for_status()
            discovery = response.json()
        _discovery_cache[issuer] = (now + DISCOVERY_TTL_SECONDS, discovery)
        return discovery

async def verify_token(token):
    issuer = (settings.OIDC_ISSUER or '').rstrip('/')
    if not issuer:
        raise RuntimeError('OIDC issuer is not configured.')
    if settings.ENVIRONMENT == 'production' and not issuer.startswith('https://'):
        raise RuntimeError('Production OIDC requires HTTPS.')
    discovery = await get_oidc_discovery(issuer)
    uri = discovery.get('jwks_uri','')
    if discovery.get('issuer') != issuer or urlparse(uri).netloc != urlparse(issuer).netloc:
        raise ValueError('OIDC discovery does not match configured issuer.')
    key = await asyncio.to_thread(key_client(issuer,uri).get_signing_key_from_jwt,token)
    claims = jwt.decode(token,key.key,algorithms=['RS256'],issuer=issuer,audience=settings.OIDC_AUDIENCE,
        options={'require':['exp','iat','iss','aud','sub']},leeway=30)
    roles = claims.get('realm_access',{}).get('roles',[])
    role = next((r for r in ('admin','reviewer','customer') if r in roles),None)
    if not role:
        raise ValueError('No support role is assigned.')
    if role in ('admin','reviewer') and settings.OIDC_REQUIRE_STAFF_MFA:
        if not set(claims.get('amr',[])) & {'mfa','otp','hwk'}:
            raise ValueError('Staff access requires an MFA-authenticated session.')
    return claims,role
