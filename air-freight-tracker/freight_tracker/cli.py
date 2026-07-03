"""Command-line interface for the International Air Freight Tracker."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime

from freight_tracker.database import DEFAULT_DB_PATH, FreightDatabase
from freight_tracker.models import Shipment, ShipmentStatus
from freight_tracker.validators import validate_awb_check_digit


def _print_shipment(shipment: Shipment, verbose: bool = False) -> None:
    print(f"  AWB:          {shipment.awb_number}")
    print(f"  Carrier:      {shipment.carrier_name}")
    print(f"  Route:        {shipment.origin_airport} -> {shipment.destination_airport}")
    print(f"  Status:       {shipment.status_label}")
    print(f"  Shipper:      {shipment.shipper}")
    print(f"  Consignee:    {shipment.consignee}")
    print(f"  Cargo:        {shipment.pieces} pcs / {shipment.weight_kg} kg")
    if shipment.commodity:
        print(f"  Commodity:    {shipment.commodity}")
    if shipment.flight_number:
        print(f"  Flight:       {shipment.flight_number}")
    if shipment.hawb_number:
        print(f"  HAWB:         {shipment.hawb_number}")
    if shipment.reference:
        print(f"  Reference:    {shipment.reference}")
    if shipment.eta:
        print(f"  ETA:          {shipment.eta.isoformat()}")
    if shipment.notes:
        print(f"  Notes:        {shipment.notes}")

    if verbose and shipment.events:
        print("\n  Tracking history:")
        for event in shipment.events:
            loc = f" @ {event.location}" if event.location else ""
            flight = f" ({event.flight_number})" if event.flight_number else ""
            print(f"    - {event.event_time.isoformat()} {event.status_label}{loc}{flight}")
            print(f"      {event.description}")
    print()


def cmd_add(args: argparse.Namespace, db: FreightDatabase) -> None:
    if not validate_awb_check_digit(args.awb):
        print(f"\n  ✗ Warning: AWB {args.awb} failed mod-7 check digit validation.\n", file=sys.stderr)

    eta = datetime.fromisoformat(args.eta) if args.eta else None
    shipment = db.create_shipment(
        awb_number=args.awb,
        origin_airport=args.origin,
        destination_airport=args.destination,
        shipper=args.shipper,
        consignee=args.consignee,
        pieces=args.pieces,
        weight_kg=args.weight,
        commodity=args.commodity or "",
        carrier_name=args.carrier,
        flight_number=args.flight,
        hawb_number=args.hawb,
        reference=args.reference,
        notes=args.notes,
        eta=eta,
    )
    print(f"\n  ✓ Shipment created: {shipment.awb_number}")
    _print_shipment(shipment, verbose=True)


def cmd_update(args: argparse.Namespace, db: FreightDatabase) -> None:
    shipment = db.get_shipment(awb_number=args.awb)
    if not shipment:
        print(f"\n  ✗ No shipment found for AWB: {args.awb}\n")
        sys.exit(1)

    event_time = datetime.fromisoformat(args.time) if args.time else None
    db.add_event(
        shipment_id=shipment.id,
        status=args.status,
        location=args.location,
        description=args.description,
        flight_number=args.flight,
        event_time=event_time,
    )
    updated = db.get_shipment(shipment_id=shipment.id)
    print(f"\n  ✓ Status updated: {ShipmentStatus.label(args.status)}")
    _print_shipment(updated, verbose=True)


def cmd_show(args: argparse.Namespace, db: FreightDatabase) -> None:
    shipment = db.get_shipment(awb_number=args.awb)
    if not shipment:
        print(f"\n  ✗ No shipment found for AWB: {args.awb}\n")
        sys.exit(1)
    print()
    _print_shipment(shipment, verbose=True)


def cmd_list(args: argparse.Namespace, db: FreightDatabase) -> None:
    shipments = db.list_shipments(
        status=args.status,
        origin=args.origin,
        destination=args.destination,
        search=args.search,
        limit=args.limit,
    )
    if not shipments:
        print("\n  No shipments found.\n")
        return

    print(f"\n  {len(shipments)} shipment(s) found:\n")
    for shipment in shipments:
        print(f"  {shipment.awb_number}  {shipment.status_label:<24} "
              f"{shipment.origin_airport} -> {shipment.destination_airport}  "
              f"{shipment.shipper} -> {shipment.consignee}")
    print()


def cmd_delete(args: argparse.Namespace, db: FreightDatabase) -> None:
    shipment = db.get_shipment(awb_number=args.awb)
    if not shipment:
        print(f"\n  ✗ No shipment found for AWB: {args.awb}\n")
        sys.exit(1)
    db.delete_shipment(shipment.id)
    print(f"\n  ✓ Shipment deleted: {shipment.awb_number}\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="freight-tracker",
        description="International Air Freight Tracker — manage AWB shipments from the CLI.",
    )
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="Path to the SQLite database file.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add", help="Create a new shipment.")
    p_add.add_argument("awb", help="AWB number, e.g. 020-12345675")
    p_add.add_argument("--origin", required=True, help="Origin airport IATA code, e.g. JFK")
    p_add.add_argument("--destination", required=True, help="Destination airport IATA code, e.g. LHR")
    p_add.add_argument("--shipper", required=True, help="Shipper name")
    p_add.add_argument("--consignee", required=True, help="Consignee name")
    p_add.add_argument("--pieces", type=int, default=1, help="Number of pieces")
    p_add.add_argument("--weight", type=float, default=0.0, help="Weight in kg")
    p_add.add_argument("--commodity", help="Commodity description")
    p_add.add_argument("--carrier", help="Carrier name (auto-detected from AWB prefix if omitted)")
    p_add.add_argument("--flight", help="Flight number")
    p_add.add_argument("--hawb", help="House AWB number")
    p_add.add_argument("--reference", help="Customer reference / booking number")
    p_add.add_argument("--notes", help="Free-text notes")
    p_add.add_argument("--eta", help="Estimated arrival time, ISO 8601")
    p_add.set_defaults(func=cmd_add)

    p_update = sub.add_parser("update", help="Add a tracking event / update shipment status.")
    p_update.add_argument("awb", help="AWB number")
    p_update.add_argument("--status", required=True, choices=ShipmentStatus.values(), help="New status")
    p_update.add_argument("--location", required=True, help="Event location (airport code or free text)")
    p_update.add_argument("--description", required=True, help="Event description")
    p_update.add_argument("--flight", help="Flight number associated with this event")
    p_update.add_argument("--time", help="Event time, ISO 8601 (defaults to now)")
    p_update.set_defaults(func=cmd_update)

    p_show = sub.add_parser("show", help="Show shipment details and tracking history.")
    p_show.add_argument("awb", help="AWB number")
    p_show.set_defaults(func=cmd_show)

    p_list = sub.add_parser("list", help="List shipments.")
    p_list.add_argument("--status", choices=ShipmentStatus.values(), help="Filter by status")
    p_list.add_argument("--origin", help="Filter by origin airport code")
    p_list.add_argument("--destination", help="Filter by destination airport code")
    p_list.add_argument("--search", help="Search AWB / shipper / consignee / reference / HAWB")
    p_list.add_argument("--limit", type=int, default=100, help="Maximum number of results")
    p_list.set_defaults(func=cmd_list)

    p_delete = sub.add_parser("delete", help="Delete a shipment.")
    p_delete.add_argument("awb", help="AWB number")
    p_delete.set_defaults(func=cmd_delete)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    db = FreightDatabase(args.db)

    try:
        args.func(args, db)
    except ValueError as exc:
        print(f"\n  ✗ Error: {exc}\n", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
