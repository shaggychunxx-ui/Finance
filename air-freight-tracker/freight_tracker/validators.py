"""AWB (Air Waybill) and airport code validation utilities."""

from __future__ import annotations

import re

# AWB format: 3-digit IATA airline prefix + 8-digit serial number, e.g. "020-12345678"
AWB_PATTERN = re.compile(r"^(\d{3})-?(\d{8})$")

# IATA airport code: exactly 3 uppercase letters
AIRPORT_PATTERN = re.compile(r"^[A-Z]{3}$")

# A small reference table of common IATA airline prefixes -> carrier name.
# Not exhaustive; unknown prefixes simply return "Unknown Carrier".
AIRLINE_PREFIXES: dict[str, str] = {
    "001": "American Airlines",
    "006": "Delta Air Lines",
    "014": "Air Canada",
    "016": "United Airlines",
    "020": "Lufthansa",
    "057": "Air France",
    "074": "KLM Royal Dutch Airlines",
    "086": "Qantas",
    "125": "British Airways",
    "160": "Cathay Pacific",
    "172": "Cargolux",
    "176": "Emirates",
    "180": "Korean Air",
    "205": "Etihad Airways",
    "297": "Qatar Airways",
    "618": "Federal Express (FedEx)",
    "784": "Singapore Airlines",
    "988": "UPS Airlines",
}


def normalize_awb(awb: str) -> str:
    """Normalize AWB to XXX-XXXXXXXX format."""
    cleaned = awb.strip().upper().replace(" ", "")
    match = AWB_PATTERN.match(cleaned)
    if not match:
        raise ValueError(
            f"Invalid AWB format: {awb!r}. Expected XXX-XXXXXXXX (3-digit prefix + 8-digit serial)."
        )
    prefix, serial = match.groups()
    return f"{prefix}-{serial}"


def validate_awb_check_digit(awb: str) -> bool:
    """Validate IATA AWB mod-7 check digit on the serial number."""
    normalized = normalize_awb(awb)
    serial = normalized.split("-")[1]
    body, check = serial[:7], int(serial[7])
    remainder = int(body) % 7
    return remainder == check


def validate_airport_code(code: str) -> str:
    """Validate and normalize a 3-letter IATA airport code.

    This only checks the format (3 uppercase letters); it does not verify
    that the code corresponds to a real, currently operating airport.
    """
    cleaned = code.strip().upper()
    if not AIRPORT_PATTERN.match(cleaned):
        raise ValueError(f"Invalid airport code: {code!r}. Expected a 3-letter IATA code (e.g. JFK).")
    return cleaned


def lookup_carrier(prefix: str) -> str:
    """Look up a carrier name from an IATA airline prefix, if known."""
    return AIRLINE_PREFIXES.get(prefix, "Unknown Carrier")
