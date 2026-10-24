"""Authentication and authorization utilities with strict server-side ownership enforcement."""
from typing import Optional
from fastapi import HTTPException, Security, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.models import Customer, Order
from app.db.session import get_db
from app.config import settings
import base64
import hashlib
import hmac
import json
import time

def issue_token(user_id: str, role: str, name: str, expires_in: int = 3600) -> str:
    """Issue a signed bearer credential for a trusted provisioning process."""
    payload = base64.urlsafe_b64encode(json.dumps({"sub": user_id, "role": role, "name": name,
        "exp": int(time.time()) + expires_in}).encode()).decode().rstrip("=")
    signature = hmac.new(settings.SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"

security = HTTPBearer(auto_error=False)

class AuthenticatedUser:
    def __init__(self, user_id: str, role: str, name: str, email: Optional[str] = None):
        self.user_id = user_id
        self.role = role # "customer" or "reviewer" or "admin"
        self.name = name
        self.email = email

    @property
    def is_reviewer(self) -> bool:
        return self.role in ("reviewer", "admin")

    @property
    def is_customer(self) -> bool:
        return self.role == "customer"

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security),
    db: AsyncSession = Depends(get_db)
) -> AuthenticatedUser:
    """
    Authenticate user from token. Supports:
    - OIDC Bearer tokens (production)
    - Signed tokens with HMAC (signed mode)
    - Demo tokens (development only): 'cust_xxx' or 'rev_xxx'
    """
    if not credentials:
        raise HTTPException(status_code=401, detail="Bearer authentication required.")
    
    token = credentials.credentials.strip()
    
    # Production: OIDC only
    if settings.AUTH_MODE == "oidc":
        if settings.ENVIRONMENT == "production":
            try:
                from app.auth.oidc import verify_token
                claims, role = await verify_token(token)
                subject = claims["sub"]
                if role == "customer":
                    customer = (await db.execute(select(Customer).where(Customer.external_auth_subject == subject))).scalar_one_or_none()
                    if not customer:
                        raise HTTPException(status_code=403, detail="Customer account is not provisioned.")
                    return AuthenticatedUser(customer.id, role, customer.name, customer.email)
                return AuthenticatedUser(subject, role, claims.get("name", "Support staff"))
            except HTTPException:
                raise
            except RuntimeError:
                raise HTTPException(status_code=503, detail="Identity service configuration is unavailable.")
            except Exception:
                raise HTTPException(status_code=401, detail="Invalid access token or required authentication assurance is missing.")
        else:
            # Development with OIDC - allow demo fallback for testing
            try:
                from app.auth.oidc import verify_token
                claims, role = await verify_token(token)
                subject = claims["sub"]
                if role == "customer":
                    customer = (await db.execute(select(Customer).where(Customer.external_auth_subject == subject))).scalar_one_or_none()
                    if not customer:
                        raise HTTPException(status_code=403, detail="Customer account is not provisioned.")
                    return AuthenticatedUser(customer.id, role, customer.name, customer.email)
                return AuthenticatedUser(subject, role, claims.get("name", "Support staff"))
            except HTTPException:
                raise
            except Exception:
                # Fall through to demo mode in development
                pass
    
    # Signed token mode (for testing without OIDC)
    if settings.AUTH_MODE == "signed":
        if settings.SECRET_KEY.startswith("super-secret-dev"):
            raise HTTPException(status_code=503, detail="Configure a private SECRET_KEY before enabling signed authentication.")
        try:
            payload, signature = token.rsplit(".", 1)
            expected = hmac.new(settings.SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(signature, expected):
                raise ValueError("Invalid signature")
            claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
            if claims["exp"] <= time.time() or claims["role"] not in ("customer", "reviewer", "admin"):
                raise ValueError("Invalid claims")
            if claims["role"] == "customer":
                customer = (await db.execute(select(Customer).where(Customer.id == claims["sub"]))).scalar_one_or_none()
                if not customer:
                    raise HTTPException(status_code=403, detail="Customer account not found.")
                return AuthenticatedUser(customer.id, claims["role"], claims["name"], customer.email)
            return AuthenticatedUser(claims["sub"], claims["role"], claims["name"])
        except (ValueError, KeyError, TypeError):
            raise HTTPException(status_code=401, detail="Invalid or expired token.")
    
    # Demo mode - ONLY in development
    if settings.AUTH_MODE == "demo" and settings.ENVIRONMENT == "development":
        if token in ("admin", "demo-admin"):
            return AuthenticatedUser(
                user_id=token,
                role="admin",
                name="System Administrator",
                email="admin@electrovault.com"
            )
        elif token.startswith("rev_"):
            return AuthenticatedUser(
                user_id=token,
                role="reviewer",
                name="Support Reviewer " + token.replace("rev_", "").title(),
                email=f"{token}@electrovault.com"
            )
        elif token.startswith("cust_"):
            result = await db.execute(select(Customer).where(Customer.id == token))
            cust = result.scalar_one_or_none()
            if not cust:
                raise HTTPException(status_code=401, detail="Unknown demo customer.")
            return AuthenticatedUser(
                user_id=cust.id,
                role="customer",
                name=cust.name,
                email=cust.email
            )
        else:
            raise HTTPException(status_code=401, detail="Invalid demo credential. Use 'cust_xxx' or 'rev_xxx' format.")
    
    raise HTTPException(status_code=401, detail="Authentication not configured for this environment.")

async def require_reviewer(
    current_user: AuthenticatedUser = Depends(get_current_user)
) -> AuthenticatedUser:
    if not current_user.is_reviewer:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: This action requires support reviewer authorization."
        )
    return current_user

async def require_admin(
    current_user: AuthenticatedUser = Depends(get_current_user)
) -> AuthenticatedUser:
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: This action requires admin authorization."
        )
    return current_user

async def verify_order_ownership(
    order_id: str,
    customer_id: str,
    db: AsyncSession
) -> Order:
    """
    Crucial security rule: An order ID provided by a customer or model does NOT
    establish access. We MUST check ownership inside the service.
    """
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order '{order_id}' not found."
        )
    if order.customer_id != customer_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: Order '{order_id}' does not belong to authenticated customer '{customer_id}'."
        )
    return order
