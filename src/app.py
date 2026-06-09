"""Procurement microservice — vendors & purchase orders.

Calls Accounting service to record purchases.
Called by Inventory service for automatic reorders.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime
from flask import Flask, request
import requests as http

from shared.health import make_health_blueprint
from shared.responses import success, error

ACCOUNTING_SERVICE_URL = os.environ.get("ACCOUNTING_SERVICE_URL", "http://accounting-service:3013")

# Valid status transitions for purchase orders
_VALID_TRANSITIONS = {
    "draft": {"approved", "cancelled"},
    "approved": {"placed", "cancelled"},
    "placed": {"received", "cancelled"},
    "partial": {"received", "cancelled"},
    "received": set(),
    "cancelled": set(),
}

_vendors: list[dict] = [
    {"id": "vendor-001", "name": "Global Supplies Inc.", "email": "orders@globalsupplies.com",
     "phone": "555-0200", "address": "5 Supply Lane", "paymentTerms": "Net 30", "status": "active"},
]

_purchase_orders: list[dict] = [
    {"id": "po-001", "poNumber": "PO-001", "vendorId": "vendor-001",
     "orderDate": "2024-01-10", "expectedDeliveryDate": "2024-01-20",
     "items": [], "totalAmount": 5000, "status": "received"},
]


def _record_journal_entry(description: str, amount: float, entries: list) -> None:
    """Post a journal entry to the Accounting service (best-effort)."""
    try:
        http.post(
            f"{ACCOUNTING_SERVICE_URL}/api/accounting/journal-entries",
            json={
                "date": datetime.utcnow().isoformat() + "Z",
                "description": description,
                "totalDebit": amount,
                "totalCredit": amount,
                "entries": entries,
            },
            timeout=3,
        )
    except Exception:
        pass


def _record_purchase(description: str, amount: float) -> None:
    """Record a purchase commitment (PO placed) in the accounting ledger."""
    _record_journal_entry(
        description,
        amount,
        [
            {"accountCode": "2000", "debit": 0, "credit": amount},   # Accounts Payable
            {"accountCode": "5000", "debit": amount, "credit": 0},   # Purchases Expense
        ],
    )


def _record_goods_receipt(description: str, amount: float) -> None:
    """Record goods receipt (PO received) — debit Inventory, credit Accounts Payable."""
    _record_journal_entry(
        description,
        amount,
        [
            {"accountCode": "1300", "debit": amount, "credit": 0},   # Inventory Asset
            {"accountCode": "2000", "debit": 0, "credit": amount},   # Accounts Payable
        ],
    )


def create_app() -> Flask:
    app = Flask(__name__)
    app.register_blueprint(make_health_blueprint("procurement-service"))

    # ------------------------------------------------------------------ #
    # Vendors
    # ------------------------------------------------------------------ #
    @app.post("/api/procurement/vendors")
    def create_vendor():
        data = request.get_json() or {}
        vendor = {
            "id": f"vendor-{datetime.utcnow().timestamp()}",
            "name": data.get("name"),
            "email": data.get("email"),
            "phone": data.get("phone"),
            "address": data.get("address"),
            "paymentTerms": data.get("paymentTerms", "Net 30"),
            "status": "active",
        }
        _vendors.append(vendor)
        return success(vendor, 201)

    @app.get("/api/procurement/vendors")
    def get_all_vendors():
        page = int(request.args.get("page", 1))
        limit = int(request.args.get("limit", 10))
        return success(_paginate(_vendors, page, limit))

    @app.get("/api/procurement/vendors/<vendor_id>")
    def get_vendor_by_id(vendor_id):
        vendor = next((v for v in _vendors if v["id"] == vendor_id), None)
        if not vendor:
            return error("VENDOR_NOT_FOUND", f"Vendor {vendor_id} not found", status_code=404)
        return success(vendor)

    @app.get("/api/procurement/vendors/<vendor_id>/performance")
    def get_vendor_performance(vendor_id):
        return success({
            "vendorId": vendor_id,
            "onTimeDeliveryRate": 95,
            "qualityScore": 4.5,
            "totalOrders": 50,
            "totalSpent": 250000,
        })

    # ------------------------------------------------------------------ #
    # Purchase Orders
    # ------------------------------------------------------------------ #
    @app.post("/api/procurement/purchase-orders")
    def create_purchase_order():
        data = request.get_json() or {}
        po = {
            "id": f"po-{datetime.utcnow().timestamp()}",
            "poNumber": f"PO-{int(datetime.utcnow().timestamp())}",
            "vendorId": data.get("vendorId"),
            "orderDate": data.get("orderDate"),
            "expectedDeliveryDate": data.get("expectedDeliveryDate"),
            "items": data.get("items", []),
            "totalAmount": data.get("totalAmount", 0),
            "status": "draft",
        }
        _purchase_orders.append(po)
        return success(po, 201)

    @app.get("/api/procurement/purchase-orders")
    def get_all_purchase_orders():
        page = int(request.args.get("page", 1))
        limit = int(request.args.get("limit", 10))
        return success(_paginate(_purchase_orders, page, limit))

    @app.get("/api/procurement/purchase-orders/<po_id>")
    def get_purchase_order_by_id(po_id):
        po = next((p for p in _purchase_orders if p["id"] == po_id), None)
        if not po:
            return error("PO_NOT_FOUND", f"Purchase order {po_id} not found", status_code=404)
        return success(po)

    def _get_po_or_404(po_id):
        po = next((p for p in _purchase_orders if p["id"] == po_id), None)
        if not po:
            return None, error("PO_NOT_FOUND", f"Purchase order {po_id} not found", status_code=404)
        return po, None

    def _check_transition(po, target_status):
        current = po.get("status", "draft")
        allowed = _VALID_TRANSITIONS.get(current, set())
        if target_status not in allowed:
            return error(
                "INVALID_STATUS_TRANSITION",
                f"Purchase order cannot transition from '{current}' to '{target_status}'",
                details={
                    "currentStatus": current,
                    "requestedStatus": target_status,
                    "allowedTransitions": list(allowed),
                },
                status_code=409,
            )
        return None

    @app.post("/api/procurement/purchase-orders/<po_id>/approve")
    def approve_purchase_order(po_id):
        po, err = _get_po_or_404(po_id)
        if err:
            return err
        transition_err = _check_transition(po, "approved")
        if transition_err:
            return transition_err
        po["status"] = "approved"
        return success({
            "id": po_id, "status": "approved",
            "approvedAt": datetime.utcnow().isoformat() + "Z",
            "message": "Purchase order approved successfully",
        })

    @app.post("/api/procurement/purchase-orders/<po_id>/place")
    def place_purchase_order(po_id):
        po, err = _get_po_or_404(po_id)
        if err:
            return err
        transition_err = _check_transition(po, "placed")
        if transition_err:
            return transition_err
        po["status"] = "placed"
        _record_purchase(f"Purchase order placed: {po_id}", po.get("totalAmount", 0))
        return success({
            "id": po_id, "status": "placed",
            "placedAt": datetime.utcnow().isoformat() + "Z",
            "message": "Purchase order placed with vendor",
        })

    @app.post("/api/procurement/purchase-orders/<po_id>/receive")
    def receive_purchase_order(po_id):
        po, err = _get_po_or_404(po_id)
        if err:
            return err
        transition_err = _check_transition(po, "received")
        if transition_err:
            return transition_err

        data = request.get_json() or {}
        received_items = data.get("items", [])
        ordered_items = po.get("items", [])

        # Validate received quantities don't exceed ordered quantities
        ordered_qty_map = {item["itemId"]: item.get("quantity", 0) for item in ordered_items if "itemId" in item}
        for item in received_items:
            item_id = item.get("itemId")
            received_qty = item.get("receivedQuantity", 0)
            ordered_qty = ordered_qty_map.get(item_id)
            if ordered_qty is not None and received_qty > ordered_qty:
                return error(
                    "QUANTITY_EXCEEDED",
                    f"Received quantity {received_qty} exceeds ordered quantity {ordered_qty} for item {item_id}",
                    status_code=400,
                )

        # Determine final status: partial if any item was under-received
        total_ordered = sum(item.get("quantity", 0) for item in ordered_items)
        total_received = sum(item.get("receivedQuantity", 0) for item in received_items)
        new_status = "partial" if (ordered_items and total_received < total_ordered) else "received"

        po["status"] = new_status
        received_at = datetime.utcnow().isoformat() + "Z"

        # Record goods receipt in accounting ledger
        amount = po.get("totalAmount", 0)
        _record_goods_receipt(f"Goods received for PO {po_id}", amount)

        return success({
            "id": po_id,
            "poNumber": po.get("poNumber"),
            "vendorId": po.get("vendorId"),
            "status": new_status,
            "previousStatus": "placed",
            "totalAmount": amount,
            "receivedDate": data.get("receivedDate"),
            "receivedBy": data.get("receivedBy"),
            "receivedAt": received_at,
            "receiptSummary": {
                "totalItemsOrdered": total_ordered,
                "totalItemsReceived": total_received,
                "fulfillmentRate": round(total_received / total_ordered * 100, 2) if total_ordered else 100.0,
                "discrepancyCount": len(data.get("discrepancies", [])),
            },
            "items": received_items,
            "discrepancies": data.get("discrepancies", []),
            "notes": data.get("notes"),
            "inventoryUpdated": True,
            "paymentTriggered": True,
            "message": "Purchase order received successfully",
            "updatedAt": received_at,
        })

    @app.post("/api/procurement/purchase-orders/<po_id>/cancel")
    def cancel_purchase_order(po_id):
        po, err = _get_po_or_404(po_id)
        if err:
            return err
        transition_err = _check_transition(po, "cancelled")
        if transition_err:
            return transition_err
        po["status"] = "cancelled"
        return success({
            "id": po_id, "status": "cancelled",
            "cancelledAt": datetime.utcnow().isoformat() + "Z",
            "message": "Purchase order cancelled",
        })

    @app.errorhandler(404)
    def not_found(_):
        return error("NOT_FOUND", "Endpoint not found", status_code=404)

    return app


def _paginate(items, page, limit):
    total = len(items)
    total_pages = max(1, (total + limit - 1) // limit)
    start = (page - 1) * limit
    return {
        "items": items[start:start + limit],
        "pagination": {
            "page": page, "limit": limit,
            "totalPages": total_pages, "totalItems": total,
            "hasNextPage": page < total_pages,
            "hasPreviousPage": page > 1,
        },
    }


if __name__ == "__main__":
    app = create_app()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 3016)), debug=False)
