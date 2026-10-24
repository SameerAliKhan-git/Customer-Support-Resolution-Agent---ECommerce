"""Mock Shipping and Carrier API simulating tracking checkpoints and return intake."""
import datetime
from typing import Dict, Any, Optional

class MockShippingService:
    """
    Simulates external carrier APIs (FedEx, UPS, DHL, USPS).
    Supports:
    - Live tracking queries
    - Realistic checkpoints (origin scan, in transit, delivered, delayed)
    - Return delivery verification at warehouse
    """
    def __init__(self):
        # Maps tracking_number -> tracking info
        self.tracking_db: Dict[str, Dict[str, Any]] = {
            "TRK_DELIVERED_01": {
                "carrier": "FedEx",
                "status": "DELIVERED",
                "delivered_at": (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=5)).isoformat(),
                "location": "San Francisco, CA",
                "events": [
                    {"time": "2026-10-15 09:30", "status": "Picked Up", "location": "Warehouse, Reno NV"},
                    {"time": "2026-10-16 14:15", "status": "In Transit", "location": "Sacramento, CA"},
                    {"time": "2026-10-17 11:42", "status": "Delivered", "location": "Front Door, San Francisco CA"}
                ]
            },
            "TRK_IN_TRANSIT_02": {
                "carrier": "UPS",
                "status": "IN_TRANSIT",
                "estimated_delivery": (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=2)).isoformat(),
                "location": "Denver, CO",
                "events": [
                    {"time": "2026-10-20 18:00", "status": "Picked Up", "location": "Fulfillment Center, Seattle WA"},
                    {"time": "2026-10-21 08:30", "status": "Arrived at Sort Facility", "location": "Denver CO"}
                ]
            },
            "TRK_DELAYED_03": {
                "carrier": "DHL",
                "status": "DELAYED",
                "estimated_delivery": (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=4)).isoformat(),
                "location": "Chicago, IL",
                "events": [
                    {"time": "2026-10-12 10:00", "status": "Picked Up", "location": "Columbus OH"},
                    {"time": "2026-10-14 02:00", "status": "Severe Weather Exception - Transit Delayed", "location": "Chicago IL"}
                ]
            },
            "RET_TRK_RECEIVED_99": {
                "carrier": "USPS",
                "status": "DELIVERED_TO_WAREHOUSE",
                "delivered_at": (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=2)).isoformat(),
                "location": "Warehouse Dock 4, Reno NV",
                "warehouse_intake_confirmed": True
            }
        }

    async def get_tracking_info(self, tracking_number: str) -> Dict[str, Any]:
        if tracking_number in self.tracking_db:
            return {
                "success": True,
                "tracking_number": tracking_number,
                "data": self.tracking_db[tracking_number]
            }
        
        # Generic synthetic tracking generator
        return {
            "success": True,
            "tracking_number": tracking_number,
            "data": {
                "carrier": "Standard Express",
                "status": "IN_TRANSIT",
                "estimated_delivery": (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1)).isoformat(),
                "location": "Regional Hub",
                "events": [
                    {"time": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M"), "status": "In Transit"}
                ]
            }
        }

mock_shipping_service = MockShippingService()
