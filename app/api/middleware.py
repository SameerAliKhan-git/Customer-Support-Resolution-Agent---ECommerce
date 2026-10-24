"""Request IDs, bounded bodies, shared request quotas and redacted request logs."""
import hashlib
import json
import logging
import time
import uuid
from datetime import datetime, timedelta
from urllib.parse import urlparse
from fastapi import Request
from fastapi.responses import JSONResponse
from app.config import settings
from app.db.session import AsyncSessionLocal
from app.db.operations import RateBucket

log=logging.getLogger('support.http')

async def quota(request):
    bucket=int(time.time()//60)
    remote=request.client.host if request.client else 'unknown'
    ident=hashlib.sha256(f'{remote}:{bucket}'.encode()).hexdigest()
    async with AsyncSessionLocal() as db:
        if db.bind.dialect.name=='postgresql':
            from sqlalchemy.dialects.postgresql import insert
        else:
            from sqlalchemy.dialects.sqlite import insert
        stmt=insert(RateBucket).values(id=ident,hits=1,expires_at=datetime.utcnow()+timedelta(minutes=2))
        count=(await db.execute(stmt.on_conflict_do_update(index_elements=['id'],set_={'hits':RateBucket.hits+1}).returning(RateBucket.hits))).scalar_one()
        await db.commit()
        return count<=settings.REQUESTS_PER_MINUTE

async def request_controls(request: Request, call_next):
    request_id=uuid.uuid4().hex
    started=time.monotonic()
    if request.method in ('POST','PUT','PATCH'):
        size=0
        chunks=[]
        async for chunk in request.stream():
            size+=len(chunk)
            if size>1_048_576:
                return JSONResponse(status_code=413,content={'detail':'Request body is too large.','request_id':request_id})
            chunks.append(chunk)
        request._body=b''.join(chunks)
    if request.url.path.startswith('/api/') and request.url.path not in ('/api/health','/api/ready'):
        if not await quota(request):
            return JSONResponse(status_code=429,content={'detail':'Request quota exceeded.'},headers={'Retry-After':'60'})
    try:
        response=await call_next(request)
    except Exception:
        # Exception text and request payloads can contain secrets or PII.
        log.error(json.dumps({'event':'request_failed','request_id':request_id}))
        response=JSONResponse(status_code=500,content={'detail':'Request failed. Use the request ID when contacting support.'})
    response.headers['X-Request-ID']=request_id
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='same-origin'
    response.headers['Cache-Control']='no-store'
    connect_src = "'self'"
    if settings.OIDC_ISSUER:
        parsed_issuer = urlparse(settings.OIDC_ISSUER)
        if parsed_issuer.scheme and parsed_issuer.netloc:
            connect_src = f"'self' {parsed_issuer.scheme}://{parsed_issuer.netloc}"
    response.headers['Content-Security-Policy'] = f"default-src 'self'; script-src 'self' https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; connect-src {connect_src}; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    if settings.ENVIRONMENT=='production':
        response.headers['Strict-Transport-Security']='max-age=31536000; includeSubDomains'
    route=request.scope.get('route')
    log.info(json.dumps({'event':'request','request_id':request_id,'method':request.method,
        'route':getattr(route,'path','unmatched'),'status':response.status_code,
        'duration_ms':round((time.monotonic()-started)*1000,2)}))
    return response
