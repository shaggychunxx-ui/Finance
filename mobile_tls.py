"""TLS for the mobile monitor PWA — local CA so phones can trust HTTPS and install the app."""

from __future__ import annotations

import ipaddress
import json
import shutil
import socket
import ssl
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from app_paths import OUTPUT


def collect_lan_ips() -> list[str]:
    ips = ["127.0.0.1"]
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if ip not in ips:
                ips.append(ip)
    except OSError:
        pass
    return ips


def _cert_covers_ips(meta_ips: list[str], needed_ips: list[str]) -> bool:
    return set(meta_ips) >= set(needed_ips)


def _load_private_key(path: Path) -> Any:
    return serialization.load_pem_private_key(path.read_bytes(), password=None)


def _ensure_ca(cert_dir: Path) -> tuple[Path, Path]:
    ca_cert = cert_dir / "mobile_ca.crt"
    ca_key = cert_dir / "mobile_ca.key"
    if ca_cert.exists() and ca_key.exists():
        return ca_cert, ca_key

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, "ETrade Trader Mobile CA"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Finance"),
        ]
    )
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .sign(key, hashes.SHA256())
    )
    ca_cert.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    ca_key.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    return ca_cert, ca_key


def _publish_ca_for_phone(ca_cert: Path) -> Path:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    phone_ca = OUTPUT / "mobile_root_ca.crt"
    shutil.copyfile(ca_cert, phone_ca)
    return phone_ca


def ensure_tls_material(cert_dir: Path, *, extra_ips: list[str] | None = None) -> tuple[Path, Path]:
    cert_dir.mkdir(parents=True, exist_ok=True)
    cert_pem = cert_dir / "mobile_monitor.crt"
    key_pem = cert_dir / "mobile_monitor.key"
    meta_path = cert_dir / "mobile_monitor.meta.json"

    needed_ips = collect_lan_ips()
    if extra_ips:
        for ip in extra_ips:
            if ip and ip not in needed_ips:
                needed_ips.append(ip)

    ca_cert, ca_key = _ensure_ca(cert_dir)
    _publish_ca_for_phone(ca_cert)

    if cert_pem.exists() and key_pem.exists() and meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if meta.get("ca") and _cert_covers_ips(list(meta.get("ips") or []), needed_ips):
                return cert_pem, key_pem
        except (json.JSONDecodeError, OSError):
            pass

    ca_key_obj = _load_private_key(ca_key)
    ca_cert_obj = x509.load_pem_x509_certificate(ca_cert.read_bytes())
    server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, "ETrade Trader Mobile"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Finance"),
        ]
    )
    now = datetime.now(timezone.utc)
    san_entries: list[x509.GeneralName] = [
        x509.DNSName("localhost"),
        x509.DNSName("etrade-trader.local"),
    ]
    for ip in needed_ips:
        try:
            san_entries.append(x509.IPAddress(ipaddress.ip_address(ip)))
        except ValueError:
            continue

    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(ca_cert_obj.subject)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=825))
        .add_extension(x509.SubjectAlternativeName(san_entries), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
    )
    cert = builder.sign(ca_key_obj, hashes.SHA256())

    cert_pem.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_pem.write_bytes(
        server_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    meta: dict[str, Any] = {
        "ips": needed_ips,
        "created": now.isoformat(),
        "cn": "ETrade Trader Mobile",
        "ca": True,
    }
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return cert_pem, key_pem


def load_ssl_context(cert_pem: Path, key_pem: Path) -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(certfile=str(cert_pem), keyfile=str(key_pem))
    return ctx