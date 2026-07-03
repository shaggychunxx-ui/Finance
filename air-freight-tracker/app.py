#!/usr/bin/env python3
"""Flask web server + REST API for the International Air Freight Tracker."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from freight_tracker.database import FreightDatabase
from freight_tracker.models import ShipmentStatus

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

app = Flask(__name__, static_folder=None)
db = FreightDatabase()


@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.route("/<path:filename>")
def static_files(filename):
    return send_from_directory(STATIC_DIR, filename)


@app.route("/api/shipments", methods=["GET"])
def list_shipments():
    status = request.args.get("status")
    origin = request.args.get("origin")
    destination = request.args.get("destination")
    search = request.args.get("search")
    limit = min(int(request.args.get("limit", 100)), 500)
    shipments = db.list_shipments(status=status, origin=origin, destination=destination, search=search, limit=limit)
    return jsonify([s.to_dict() for s in shipments])


@app.route("/api/shipments", methods=["POST"])
def create_shipment():
    payload = request.get_json(force=True, silent=True) or {}
    try:
        eta = datetime.fromisoformat(payload["eta"]) if payload.get("eta") else None
        shipment = db.create_shipment(
            awb_number=payload["awb_number"],
            origin_airport=payload["origin_airport"],
            destination_airport=payload["destination_airport"],
            shipper=payload["shipper"],
            consignee=payload["consignee"],
            pieces=int(payload.get("pieces", 1)),
            weight_kg=float(payload.get("weight_kg", 0.0)),
            commodity=payload.get("commodity", ""),
            carrier_name=payload.get("carrier_name"),
            flight_number=payload.get("flight_number"),
            hawb_number=payload.get("hawb_number"),
            reference=payload.get("reference"),
            notes=payload.get("notes"),
            eta=eta,
        )
    except KeyError as exc:
        return jsonify({"error": f"Missing required field: {exc.args[0]}"}), 400
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    return jsonify(shipment.to_dict()), 201


@app.route("/api/shipments/<int:shipment_id>", methods=["GET"])
def get_shipment(shipment_id: int):
    shipment = db.get_shipment(shipment_id=shipment_id)
    if not shipment:
        return jsonify({"error": "Shipment not found"}), 404
    return jsonify(shipment.to_dict())


@app.route("/api/shipments/<int:shipment_id>", methods=["DELETE"])
def delete_shipment(shipment_id: int):
    deleted = db.delete_shipment(shipment_id)
    if not deleted:
        return jsonify({"error": "Shipment not found"}), 404
    return jsonify({"success": True})


@app.route("/api/shipments/<int:shipment_id>/events", methods=["POST"])
def add_event(shipment_id: int):
    payload = request.get_json(force=True, silent=True) or {}
    try:
        event_time = datetime.fromisoformat(payload["event_time"]) if payload.get("event_time") else None
        event = db.add_event(
            shipment_id=shipment_id,
            status=payload["status"],
            location=payload["location"],
            description=payload["description"],
            flight_number=payload.get("flight_number"),
            event_time=event_time,
        )
    except KeyError as exc:
        return jsonify({"error": f"Missing required field: {exc.args[0]}"}), 400
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    return jsonify(event.to_dict()), 201


@app.route("/api/statuses", methods=["GET"])
def list_statuses():
    return jsonify([{"value": s.value, "label": ShipmentStatus.label(s.value)} for s in ShipmentStatus])


if __name__ == "__main__":
    app.run(debug=True, port=5000)
