"""Seed synthetic database records for ElectroVault Global."""
import asyncio
import datetime
from sqlalchemy import select

from app.db.session import async_engine, AsyncSessionLocal, init_db
from app.db.models import Customer, Order, ReturnRecord, PaymentRecord, Ticket
from app.policies.rag_engine import policy_rag_service

async def seed():
    print("Initializing database tables...")
    await init_db()
    
    async with AsyncSessionLocal() as session:
        # Check if already seeded
        res = await session.execute(select(Customer))
        if res.scalars().first():
            print("Database already contains records. Refreshing policies...")
            policy_count = await policy_rag_service.ingest_directory("app/policies/documents", session)
            print(f"Ingested {policy_count} policy chunks.")
            return

        print("Seeding customers...")
        customers = [
            Customer(
                id="cust_1001",
                external_auth_subject="auth0|cust_1001",
                name="Alice Johnson",
                email="alice.johnson@example.com",
                phone="+1-555-0101",
                created_at=datetime.datetime.utcnow() - datetime.timedelta(days=90)
            ),
            Customer(
                id="cust_1002",
                external_auth_subject="auth0|cust_1002",
                name="Bob Smith",
                email="bob.smith@example.com",
                phone="+1-555-0102",
                created_at=datetime.datetime.utcnow() - datetime.timedelta(days=120)
            ),
            Customer(
                id="cust_1003",
                external_auth_subject="auth0|cust_1003",
                name="Carol White",
                email="carol.white@example.com",
                phone="+1-555-0103",
                created_at=datetime.datetime.utcnow() - datetime.timedelta(days=60)
            ),
            Customer(
                id="cust_1004",
                external_auth_subject="auth0|cust_1004",
                name="David Miller",
                email="david.miller@example.com",
                phone="+1-555-0104",
                created_at=datetime.datetime.utcnow() - datetime.timedelta(days=40)
            ),
            Customer(
                id="cust_1005",
                external_auth_subject="auth0|cust_1005",
                name="Emma Davis",
                email="emma.davis@example.com",
                phone="+1-555-0105",
                created_at=datetime.datetime.utcnow() - datetime.timedelta(days=25)
            ),
        ]
        session.add_all(customers)
        await session.flush()

        print("Seeding orders, returns, payments...")
        now = datetime.datetime.utcnow()
        
        # 1. ord_1001 (Alice): Headphones returned and inspection passed. Eligible for refund!
        ord_1001 = Order(
            id="ord_1001",
            customer_id="cust_1001",
            currency="USD",
            total_amount_minor=24999, # $249.99
            status="RETURNED",
            items=[{"sku": "HDPH-NC-01", "name": "AcousticPro Wireless ANC Headphones", "qty": 1, "price_minor": 24999}],
            order_date=now - datetime.timedelta(days=18),
            delivery_date=now - datetime.timedelta(days=12)
        )
        ret_1001 = ReturnRecord(
            id="ret_1001",
            order_id="ord_1001",
            customer_id="cust_1001",
            status="INSPECTION_PASSED",
            tracking_number="RET_TRK_RECEIVED_99",
            carrier="USPS",
            return_reason="Too tight on ears",
            inspection_notes="Unit pristine, all cables and retail packaging present. Serial number verified.",
            received_at=now - datetime.timedelta(days=2)
        )
        pay_1001 = PaymentRecord(
            id="pay_1001",
            order_id="ord_1001",
            customer_id="cust_1001",
            amount_minor=24999,
            currency="USD",
            payment_method="VISA_4242",
            status="CAPTURED",
            refunded_amount_minor=0,
            reserved_refund_minor=0,
            transaction_reference="tx_vis_90210"
        )

        # 2. ord_1002 (Bob): Delivered 45 days ago. Past 30-day return window!
        ord_1002 = Order(
            id="ord_1002",
            customer_id="cust_1002",
            currency="USD",
            total_amount_minor=8999, # $89.99
            status="DELIVERED",
            items=[{"sku": "DOCK-USB-C", "name": "ThunderBolt 12-in-1 Dual 4K Dock", "qty": 1, "price_minor": 8999}],
            order_date=now - datetime.timedelta(days=50),
            delivery_date=now - datetime.timedelta(days=45)
        )
        pay_1002 = PaymentRecord(
            id="pay_1002",
            order_id="ord_1002",
            customer_id="cust_1002",
            amount_minor=8999,
            currency="USD",
            payment_method="MASTERCARD_8811",
            status="CAPTURED",
            refunded_amount_minor=0,
            reserved_refund_minor=0,
            transaction_reference="tx_mc_44122"
        )

        # 3. ord_1003 (Carol): In transit.
        ord_1003 = Order(
            id="ord_1003",
            customer_id="cust_1003",
            currency="USD",
            total_amount_minor=14900, # $149.00
            status="SHIPPED",
            items=[{"sku": "KB-MECH-RGB", "name": "VortexPro Mechanical Gaming Keyboard", "qty": 1, "price_minor": 14900}],
            order_date=now - datetime.timedelta(days=3),
            delivery_date=None
        )
        pay_1003 = PaymentRecord(
            id="pay_1003",
            order_id="ord_1003",
            customer_id="cust_1003",
            amount_minor=14900,
            currency="USD",
            payment_method="AMEX_1004",
            status="CAPTURED",
            refunded_amount_minor=0,
            reserved_refund_minor=0,
            transaction_reference="tx_amx_55112"
        )

        # 4. ord_1004 (David): Delivered 3 days ago. Damaged item on arrival.
        ord_1004 = Order(
            id="ord_1004",
            customer_id="cust_1004",
            currency="USD",
            total_amount_minor=32000, # $320.00
            status="DELIVERED",
            items=[{"sku": "MON-4K-27", "name": "UltraSharp 27-inch 4K IPS Monitor", "qty": 1, "price_minor": 32000}],
            order_date=now - datetime.timedelta(days=6),
            delivery_date=now - datetime.timedelta(days=3)
        )
        pay_1004 = PaymentRecord(
            id="pay_1004",
            order_id="ord_1004",
            customer_id="cust_1004",
            amount_minor=32000,
            currency="USD",
            payment_method="PAYPAL",
            status="CAPTURED",
            refunded_amount_minor=0,
            reserved_refund_minor=0,
            transaction_reference="tx_pp_77221"
        )

        # 5. ord_1005 (Emma): Return in transit, not yet received by warehouse!
        ord_1005 = Order(
            id="ord_1005",
            customer_id="cust_1005",
            currency="USD",
            total_amount_minor=19950, # $199.50
            status="RETURNED",
            items=[{"sku": "CAM-SEC-02", "name": "DefenderCam Smart Wireless Security Pack", "qty": 1, "price_minor": 19950}],
            order_date=now - datetime.timedelta(days=14),
            delivery_date=now - datetime.timedelta(days=9)
        )
        ret_1005 = ReturnRecord(
            id="ret_1005",
            order_id="ord_1005",
            customer_id="cust_1005",
            status="IN_TRANSIT",
            tracking_number="TRK_IN_TRANSIT_02",
            carrier="UPS",
            return_reason="Bought wrong model",
            inspection_notes=None,
            received_at=None
        )
        pay_1005 = PaymentRecord(
            id="pay_1005",
            order_id="ord_1005",
            customer_id="cust_1005",
            amount_minor=19950,
            currency="USD",
            payment_method="VISA_1122",
            status="CAPTURED",
            refunded_amount_minor=0,
            reserved_refund_minor=0,
            transaction_reference="tx_vis_66331"
        )

        # 6. ord_1006 (Alice): Shipping delay inquiry
        ord_1006 = Order(
            id="ord_1006",
            customer_id="cust_1001",
            currency="USD",
            total_amount_minor=4500, # $45.00
            status="SHIPPED",
            items=[{"sku": "MOU-ERG-01", "name": "ErgoGrip Wireless Vertical Mouse", "qty": 1, "price_minor": 4500}],
            order_date=now - datetime.timedelta(days=10),
            delivery_date=None
        )
        pay_1006 = PaymentRecord(
            id="pay_1006",
            order_id="ord_1006",
            customer_id="cust_1001",
            amount_minor=4500,
            currency="USD",
            payment_method="VISA_4242",
            status="CAPTURED",
            refunded_amount_minor=0,
            reserved_refund_minor=0,
            transaction_reference="tx_vis_90212"
        )

        # 7. ord_1007 (Carol): Inspection failed
        ord_1007 = Order(
            id="ord_1007",
            customer_id="cust_1003",
            currency="USD",
            total_amount_minor=7500, # $75.00
            status="RETURNED",
            items=[{"sku": "SSD-EXT-1TB", "name": "PocketSpeed 1TB USB-C NVMe SSD", "qty": 1, "price_minor": 7500}],
            order_date=now - datetime.timedelta(days=15),
            delivery_date=now - datetime.timedelta(days=10)
        )
        ret_1007 = ReturnRecord(
            id="ret_1007",
            order_id="ord_1007",
            customer_id="cust_1003",
            status="INSPECTION_FAILED",
            tracking_number="RET_TRK_RECEIVED_99",
            carrier="USPS",
            return_reason="No longer needed",
            inspection_notes="Drive casing cracked and serial number sticker peeled off. Rejected.",
            received_at=now - datetime.timedelta(days=3)
        )
        pay_1007 = PaymentRecord(
            id="pay_1007",
            order_id="ord_1007",
            customer_id="cust_1003",
            amount_minor=7500,
            currency="USD",
            payment_method="AMEX_1004",
            status="CAPTURED",
            refunded_amount_minor=0,
            reserved_refund_minor=0,
            transaction_reference="tx_amx_55115"
        )

        # 8. ord_1008 (David): Prepared specifically for Timeout & Reconciliation test (Scenario C)
        ord_1008 = Order(
            id="ord_1008",
            customer_id="cust_1004",
            currency="USD",
            total_amount_minor=12000, # $120.00
            status="RETURNED",
            items=[{"sku": "MIC-USB-01", "name": "StreamBroadcast Pro USB Mic", "qty": 1, "price_minor": 12000}],
            order_date=now - datetime.timedelta(days=12),
            delivery_date=now - datetime.timedelta(days=8)
        )
        ret_1008 = ReturnRecord(
            id="ret_1008",
            order_id="ord_1008",
            customer_id="cust_1004",
            status="INSPECTION_PASSED",
            tracking_number="RET_TRK_RECEIVED_99",
            carrier="USPS",
            return_reason="Upgrading setup",
            inspection_notes="Microphone in original condition.",
            received_at=now - datetime.timedelta(days=2)
        )
        pay_1008 = PaymentRecord(
            id="pay_1008",
            order_id="ord_1008",
            customer_id="cust_1004",
            amount_minor=12000,
            currency="USD",
            payment_method="PAYPAL",
            status="CAPTURED",
            refunded_amount_minor=0,
            reserved_refund_minor=0,
            transaction_reference="tx_pp_77225"
        )

        # 9. ord_high_01 (David): High-value order ($750) for testing >$500 damage escalation
        ord_high_01 = Order(
            id="ord_high_01",
            customer_id="cust_1004",
            currency="USD",
            total_amount_minor=75000, # $750.00
            status="DELIVERED",
            items=[{"sku": "LAPTOP-PRO", "name": "Precision Studio Pro Laptop", "qty": 1, "price_minor": 75000}],
            order_date=now - datetime.timedelta(days=5),
            delivery_date=now - datetime.timedelta(days=2)
        )
        pay_high_01 = PaymentRecord(
            id="pay_high_01",
            order_id="ord_high_01",
            customer_id="cust_1004",
            amount_minor=75000,
            currency="USD",
            payment_method="VISA_4242",
            status="CAPTURED",
            refunded_amount_minor=0,
            reserved_refund_minor=0,
            transaction_reference="tx_vis_90881"
        )

        session.add_all([
            ord_1001, ret_1001, pay_1001,
            ord_1002, pay_1002,
            ord_1003, pay_1003,
            ord_1004, pay_1004,
            ord_1005, ret_1005, pay_1005,
            ord_1006, pay_1006,
            ord_1007, ret_1007, pay_1007,
            ord_1008, ret_1008, pay_1008,
            ord_high_01, pay_high_01
        ])
        await session.flush()


        print("Seeding initial tickets...")
        tickets = [
            Ticket(
                id="tkt_1001",
                customer_id="cust_1001",
                order_id="ord_1001",
                title="Refund for returned headphones",
                category="REFUND_REQUEST",
                status="OPEN",
                priority="HIGH",
                customer_message="I returned my headphones last week, but I still haven't received my refund.",
                notes=[{"author": "SYSTEM", "text": "Ticket created via customer web portal", "time": now.isoformat()}]
            ),
            Ticket(
                id="tkt_1002",
                customer_id="cust_1002",
                order_id="ord_1002",
                title="Return and refund request for USB dock",
                category="REFUND_REQUEST",
                status="OPEN",
                priority="MEDIUM",
                customer_message="I would like to return this USB dock and get my money back.",
                notes=[{"author": "SYSTEM", "text": "Ticket created via customer web portal", "time": now.isoformat()}]
            ),
            Ticket(
                id="tkt_1003",
                customer_id="cust_1003",
                order_id="ord_1003",
                title="Where is my gaming keyboard?",
                category="ORDER_STATUS",
                status="OPEN",
                priority="MEDIUM",
                customer_message="Can you give me an update on where my keyboard is right now?",
                notes=[{"author": "SYSTEM", "text": "Ticket created via customer web portal", "time": now.isoformat()}]
            )
        ]
        session.add_all(tickets)
        await session.commit()
        
        print("Ingesting policy documents into RAG vector store...")
        policy_count = await policy_rag_service.ingest_directory("app/policies/documents", session)
        print(f"Successfully ingested {policy_count} policy chunks with citations.")

    print("Seed data completed successfully!")

if __name__ == "__main__":
    asyncio.run(seed())
