"""Authenticated portal context and operator health metrics."""
from datetime import datetime, timedelta
from fastapi import APIRouter,Depends,HTTPException
from sqlalchemy import select,func
from app.config import settings
from app.auth.security import get_current_user,require_reviewer
from app.db.session import AsyncSessionLocal
from app.db.models import RefundOperation,Ticket
from app.db.operations import WorkItem,ExecutionLease
router=APIRouter()

@router.get('/session/config')
async def session_config():
    return {'auth_mode':settings.AUTH_MODE,'demo':settings.AUTH_MODE=='demo' and settings.ENVIRONMENT=='development',
        'async_workflows':settings.ASYNC_WORKFLOWS,'issuer':settings.OIDC_ISSUER,'client_id':settings.OIDC_CLIENT_ID,
        'audience':settings.OIDC_AUDIENCE}

@router.get('/session/me')
async def me(user=Depends(get_current_user)):
    return {'id':user.user_id,'name':user.name,'role':user.role}

@router.get('/ready')
async def ready():
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(select(func.count()).select_from(Ticket))
            if settings.ASYNC_WORKFLOWS:
                heartbeat=await db.get(ExecutionLease,'worker-heartbeat')
                if not heartbeat or heartbeat.expires_at<=datetime.utcnow():
                    raise ValueError('worker unavailable')
    except Exception:
        raise HTTPException(503,'Application dependencies are not ready.')
    return {'status':'ready'}

from app.db.models import RefundOperation,Ticket,Approval
from app.db.operations import WorkItem,ExecutionLease

@router.get('/metrics')
async def metrics(user=Depends(require_reviewer)):
    async with AsyncSessionLocal() as db:
        now = datetime.utcnow()
        jobs = dict((await db.execute(select(WorkItem.status, func.count()).group_by(WorkItem.status))).all())
        refunds = dict((await db.execute(select(RefundOperation.status, func.count()).group_by(RefundOperation.status))).all())
        escalated = (await db.execute(select(func.count()).select_from(Ticket).where(Ticket.status == 'ESCALATED'))).scalar_one()
        overdue = (await db.execute(select(func.count()).select_from(Ticket).where(Ticket.due_at < now, Ticket.status.not_in(['CLOSED', 'RESOLVED'])))).scalar_one()
        pending_approvals = (await db.execute(select(func.count()).select_from(Approval).where(Approval.decision == 'PENDING'))).scalar_one()
        pending_reconciliations = refunds.get('PENDING_RECONCILIATION', 0)

        # Worker heartbeat age
        heartbeat = await db.get(ExecutionLease, 'worker-heartbeat')
        heartbeat_age = round((now - heartbeat.expires_at + timedelta(seconds=120)).total_seconds(), 2) if heartbeat else None

        # Oldest ready job age
        oldest_ready = (await db.execute(select(func.min(WorkItem.available_at)).where(WorkItem.status == 'READY'))).scalar_one_or_none()
        oldest_job_age = round((now - oldest_ready).total_seconds(), 2) if oldest_ready and oldest_ready < now else 0.0

        return {
            'jobs': jobs,
            'refunds': refunds,
            'escalated_tickets': escalated,
            'overdue_tickets': overdue,
            'pending_approvals': pending_approvals,
            'pending_reconciliations': pending_reconciliations,
            'worker_heartbeat_age_seconds': heartbeat_age,
            'oldest_ready_job_age_seconds': oldest_job_age
        }
