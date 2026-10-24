"""Pydantic schemas for customers."""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

class CustomerBase(BaseModel):
    name: str
    email: str = Field(..., description="Customer email address")
    phone: Optional[str] = None


class CustomerCreate(CustomerBase):
    pass

class CustomerResponse(CustomerBase):
    id: str
    created_at: datetime

    class Config:
        from_attributes = True
