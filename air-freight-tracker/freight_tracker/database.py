"""SQLite persistence layer for the Air Freight Tracker."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from freight_tracker.models import Shipment, ShipmentStatus, TrackingEvent
from freight_tracker.validators import (
    lookup_carrier,
    normalize_awb,
    validate_airport_code,
)

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "freight_tracker.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS shipments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    awb_number TEXT NOT NULL UNIQUE,
    airline_prefix TEXT NOT NULL,
    carrier_name TEXT NOT NULL,
    origin_airport TEXT NOT NULL,
    destination_airport TEXT NOT NULL,
    shipper TEXT NOT NULL,
    consignee TEXT NOT NULL,
    pieces INTEGER NOT NULL DEFAULT 1,
    weight_kg REAL NOT NULL DEFAULT 0,
    commodity TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    flight_number TEXT,
    hawb_number TEXT,
    reference TEXT,
    notes TEXT,
    eta TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tracking_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shipment_id INTEGER NOT NULL REFERENCES shipments(id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    location TEXT NOT NULL,
    description TEXT NOT NULL,
    flight_number TEXT,
    event_time TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_shipment_id ON tracking_events(shipment_id);
CREATE INDEX IF NOT EXISTS idx_shipments_status ON shipments(status);
"""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_event_location(location: str) -> str:
    """Normalize a tracking event location.

    3-letter tokens are treated as IATA airport codes and validated/upper-cased;
    anything else (e.g. a city name, warehouse, or customs facility) is passed
    through as free text.
    """
    stripped = location.strip()
    if len(stripped) == 3:
        return validate_airport_code(stripped)
    return stripped


class FreightDatabase:
    """Manages persistence of shipments and tracking events in SQLite."""

    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH):
        self.db_path = Path(db_path)
        self._init_schema()

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Row <-> model conversion
    # ------------------------------------------------------------------

    def _row_to_event(self, row: sqlite3.Row) -> TrackingEvent:
        return TrackingEvent(
            id=row["id"],
            shipment_id=row["shipment_id"],
            status=row["status"],
            location=row["location"],
            description=row["description"],
            flight_number=row["flight_number"],
            event_time=row["event_time"],
            created_at=row["created_at"],
        )

    def _row_to_shipment(self, row: sqlite3.Row, events: list[TrackingEvent]) -> Shipment:
        return Shipment(
            id=row["id"],
            awb_number=row["awb_number"],
            airline_prefix=row["airline_prefix"],
            carrier_name=row["carrier_name"],
            origin_airport=row["origin_airport"],
            destination_airport=row["destination_airport"],
            shipper=row["shipper"],
            consignee=row["consignee"],
            pieces=row["pieces"],
            weight_kg=row["weight_kg"],
            commodity=row["commodity"],
            status=row["status"],
            flight_number=row["flight_number"],
            hawb_number=row["hawb_number"],
            reference=row["reference"],
            notes=row["notes"],
            eta=row["eta"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            events=events,
        )

    def _load_events(self, conn: sqlite3.Connection, shipment_id: int) -> list[TrackingEvent]:
        rows = conn.execute(
            "SELECT * FROM tracking_events WHERE shipment_id = ? ORDER BY event_time ASC, id ASC",
            (shipment_id,),
        ).fetchall()
        return [self._row_to_event(r) for r in rows]

    # ------------------------------------------------------------------
    # Shipment operations
    # ------------------------------------------------------------------

    def create_shipment(
        self,
        awb_number: str,
        origin_airport: str,
        destination_airport: str,
        shipper: str,
        consignee: str,
        pieces: int = 1,
        weight_kg: float = 0.0,
        commodity: str = "",
        carrier_name: str | None = None,
        flight_number: str | None = None,
        hawb_number: str | None = None,
        reference: str | None = None,
        notes: str | None = None,
        eta: datetime | None = None,
    ) -> Shipment:
        awb = normalize_awb(awb_number)
        origin = validate_airport_code(origin_airport)
        destination = validate_airport_code(destination_airport)
        prefix = awb.split("-")[0]
        carrier = carrier_name or lookup_carrier(prefix)
        now = _utcnow()

        with self._connect() as conn:
            try:
                cursor = conn.execute(
                    """
                    INSERT INTO shipments (
                        awb_number, airline_prefix, carrier_name,
                        origin_airport, destination_airport,
                        shipper, consignee, pieces, weight_kg, commodity,
                        status, flight_number, hawb_number, reference, notes, eta,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        awb,
                        prefix,
                        carrier,
                        origin,
                        destination,
                        shipper,
                        consignee,
                        pieces,
                        weight_kg,
                        commodity,
                        ShipmentStatus.BOOKED.value,
                        flight_number,
                        hawb_number,
                        reference,
                        notes,
                        eta.isoformat() if eta else None,
                        now.isoformat(),
                        now.isoformat(),
                    ),
                )
                shipment_id = cursor.lastrowid
                conn.execute(
                    """
                    INSERT INTO tracking_events (
                        shipment_id, status, location, description, flight_number, event_time, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        shipment_id,
                        ShipmentStatus.BOOKED.value,
                        origin,
                        f"Shipment booked — {pieces} piece(s), {weight_kg} kg",
                        flight_number,
                        now.isoformat(),
                        now.isoformat(),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"AWB {awb} already exists in the system.") from exc

            row = conn.execute("SELECT * FROM shipments WHERE id = ?", (shipment_id,)).fetchone()
            events = self._load_events(conn, shipment_id)
            return self._row_to_shipment(row, events)

    def get_shipment(
        self, shipment_id: int | None = None, awb_number: str | None = None
    ) -> Shipment | None:
        if shipment_id is None and awb_number is None:
            raise ValueError("Either shipment_id or awb_number must be provided.")

        with self._connect() as conn:
            if shipment_id is not None:
                row = conn.execute("SELECT * FROM shipments WHERE id = ?", (shipment_id,)).fetchone()
            else:
                awb = normalize_awb(awb_number)
                row = conn.execute("SELECT * FROM shipments WHERE awb_number = ?", (awb,)).fetchone()

            if not row:
                return None

            events = self._load_events(conn, row["id"])
            return self._row_to_shipment(row, events)

    def list_shipments(
        self,
        status: str | None = None,
        origin: str | None = None,
        destination: str | None = None,
        search: str | None = None,
        limit: int = 100,
    ) -> list[Shipment]:
        query = "SELECT * FROM shipments WHERE 1=1"
        params: list[object] = []

        if status:
            query += " AND status = ?"
            params.append(status)
        if origin:
            query += " AND origin_airport = ?"
            params.append(origin.strip().upper())
        if destination:
            query += " AND destination_airport = ?"
            params.append(destination.strip().upper())
        if search:
            query += (
                " AND (awb_number LIKE ? OR shipper LIKE ? OR consignee LIKE ?"
                " OR reference LIKE ? OR hawb_number LIKE ?)"
            )
            like = f"%{search.strip()}%"
            params.extend([like, like, like, like, like])

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
            shipments = []
            for row in rows:
                events = self._load_events(conn, row["id"])
                shipments.append(self._row_to_shipment(row, events))
            return shipments

    def delete_shipment(self, shipment_id: int) -> bool:
        with self._connect() as conn:
            conn.execute("DELETE FROM tracking_events WHERE shipment_id = ?", (shipment_id,))
            cursor = conn.execute("DELETE FROM shipments WHERE id = ?", (shipment_id,))
            return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # Tracking event operations
    # ------------------------------------------------------------------

    def add_event(
        self,
        shipment_id: int,
        status: str,
        location: str,
        description: str,
        flight_number: str | None = None,
        event_time: datetime | None = None,
        update_shipment_status: bool = True,
    ) -> TrackingEvent:
        if status not in {s.value for s in ShipmentStatus}:
            raise ValueError(f"Invalid status: {status}")

        location = _normalize_event_location(location)
        now = _utcnow()
        event_dt = event_time or now

        with self._connect() as conn:
            exists = conn.execute("SELECT id FROM shipments WHERE id = ?", (shipment_id,)).fetchone()
            if not exists:
                raise ValueError(f"Shipment ID {shipment_id} not found.")

            cursor = conn.execute(
                """
                INSERT INTO tracking_events (
                    shipment_id, status, location, description, flight_number, event_time, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    shipment_id,
                    status,
                    location,
                    description,
                    flight_number,
                    event_dt.isoformat(),
                    now.isoformat(),
                ),
            )

            if update_shipment_status:
                conn.execute(
                    "UPDATE shipments SET status = ?, updated_at = ? WHERE id = ?",
                    (status, now.isoformat(), shipment_id),
                )

            row = conn.execute("SELECT * FROM tracking_events WHERE id = ?", (cursor.lastrowid,)).fetchone()
            return self._row_to_event(row)
