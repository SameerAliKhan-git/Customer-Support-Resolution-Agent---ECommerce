"""Explicit ecommerce gateway contract; all endpoints are configured server-side."""
import httpx
from pydantic import BaseModel,ConfigDict,Field
from app.config import settings

class Shipment(BaseModel):
    model_config=ConfigDict(extra='forbid')
    order_id:str
    status:str
    carrier:str|None=None
    tracking_number:str|None=None
    estimated_delivery:str|None=None
    location:str|None=None
    source:str='ecommerce_gateway'

async def request(method,path,**kwargs):
    if not settings.INTEGRATION_BASE_URL or not settings.INTEGRATION_API_TOKEN:
        raise ValueError('Ecommerce integration is not configured.')
    if settings.ENVIRONMENT=='production' and not settings.INTEGRATION_BASE_URL.startswith('https://'):
        raise ValueError('Production integrations require HTTPS.')
    async with httpx.AsyncClient(base_url=settings.INTEGRATION_BASE_URL.rstrip('/')+'/',timeout=10,follow_redirects=False) as client:
        response=await client.request(method,path,headers={'Authorization':f'Bearer {settings.INTEGRATION_API_TOKEN}'},**kwargs)
        response.raise_for_status()
        return response.json()

async def shipment(order):
    from urllib.parse import quote
    if settings.INTEGRATION_BASE_URL:
        result=Shipment.model_validate(await request('GET',f'orders/{quote(order.id,safe="")}/shipment'))
        if result.order_id!=order.id:
            raise ValueError('Shipment response does not match the owned order.')
        return result.model_dump()
    if order.id=='ord_1003' and settings.SEED_DEMO_DATA:
        from mock_services.shipping.mock_shipping_api import mock_shipping_service
        tracking=await mock_shipping_service.get_tracking_info('TRK_IN_TRANSIT_02')
        return Shipment(order_id=order.id,status=tracking['data']['status'],carrier=tracking['data']['carrier'],
            estimated_delivery=tracking['data'].get('estimated_delivery'),location=tracking['data'].get('location'),
            tracking_number='TRK_IN_TRANSIT_02',source='mock_shipping').model_dump()
    return Shipment(order_id=order.id,status=order.status,source='order_record').model_dump()

async def sync_ticket(payload,key):
    from urllib.parse import quote
    return await request('PUT',f'tickets/{quote(payload["ticket_id"],safe="")}',json={**payload,'idempotency_key':key})
