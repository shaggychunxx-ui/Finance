"""Shipment & tracking event data models for the Air Freight Tracker."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class ShipmentStatus(str, Enum):
    """Lifecycle states of an air freight shipment."""

    BOOKED = "booked"
    RECEIVED_AT_ORIGIN = "received_at_origin"
    EXPORT_CUSTOMS = "export_customs"
    DEPARTED = "departed"
    IN_TRANSIT = "in_transit"
    ARRIVED = "arrived"
    IMPORT_CUSTOMS = "import_customs"
    OUT_FOR_DELIVERY = "out_for_delivery"
    DELIVERED = "delivered"
    EXCEPTION = "exception"
    CANCELLED = "cancelled"

    @classmethod
    def label(cls, value: str) -> str:
        labels = {
            "booked": "Booked",
            "received_at_origin": "Received at Origin",
            "export_customs": "Export Customs",
            "departed": "Departed",
            "in_transit": "In Transit",
            "arrived": "Arrived at Destination",
            "import_customs": "Import Customs",
            "out_for_delivery": "Out for Delivery",
            "delivered": "Delivered",
            "exception": "Exception",
            "cancelled": "Cancelled",
        }
        return labels.get(value, value.replace("_", " ").title())

    @classmethod
    def values(cls) -> list[str]:
        return [s.value for s in cls]


def _parse_dt(value: Any) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


@dataclass
class TrackingEvent:
    """A single tracking milestone recorded against a shipment."""

    id: int | None
    shipment_id: int
    status: str
    location: str
    description: str
    flight_number: str | None = None
    event_time: datetime | None = None
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        self.event_time = _parse_dt(self.event_time)
        self.created_at = _parse_dt(self.created_at)

    @property
    def status_label(self) -> str:
        return ShipmentStatus.label(self.status)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "shipment_id": self.shipment_id,
            "status": self.status,
            "status_label": self.status_label,
            "location": self.location,
            "description": self.description,
            "flight_number": self.flight_number,
            "event_time": self.event_time.isoformat() if self.event_time else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


@dataclass
class Shipment:
    """An air freight shipment tracked by AWB (Air Waybill) number."""

    id: int | None
    awb_number: str
    airline_prefix: str
    carrier_name: str
    origin_airport: str
    destination_airport: str
    shipper: str
    consignee: str
    pieces: int
    weight_kg: float
    commodity: str
    status: str
    flight_number: str | None = None
    hawb_number: str | None = None
    reference: str | None = None
    notes: str | None = None
    eta: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    events: list[TrackingEvent] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.eta = _parse_dt(self.eta)
        self.created_at = _parse_dt(self.created_at)
        self.updated_at = _parse_dt(self.updated_at)

    @property
    def status_label(self) -> str:
        return ShipmentStatus.label(self.status)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "awb_number": self.awb_number,
            "airline_prefix": self.airline_prefix,
            "carrier_name": self.carrier_name,
            "origin_airport": self.origin_airport,
            "destination_airport": self.destination_airport,
            "shipper": self.shipper,
            "consignee": self.consignee,
            "pieces": self.pieces,
            "weight_kg": self.weight_kg,
            "commodity": self.commodity,
            "status": self.status,
            "status_label": self.status_label,
            "flight_number": self.flight_number,
            "hawb_number": self.hawb_number,
            "reference": self.reference,
            "notes": self.notes,
            "eta": self.eta.isoformat() if self.eta else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "events": [e.to_dict() for e in self.events],
        }
