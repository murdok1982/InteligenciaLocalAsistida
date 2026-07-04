# -*- coding: utf-8 -*-
"""
HISPANSHIELD — GUARDIAN DE PROPIEDAD INTELECTUAL
Propiedad de HispanShield (Legion de Ciberdefensa)
General Murdok (Gustavo Lobato Clara)
"""
import os
import sys
import socket
import getpass
import platform
from datetime import datetime, timezone

SEAL = """
=============================================
   HISPANSHIELD — LEGION DE CIBERDEFENSA
   PROPIEDAD DE GENERAL MURDOK (GUSTAVO LOBATO CLARA)
   TODOS LOS DERECHOS RESERVADOS
=============================================
"""


def audit():
    try:
        hostname = socket.gethostname()
        ip = socket.gethostbyname(hostname)
    except OSError:
        hostname = "unknown"
        ip = "0.0.0.0"
    return {
        "usuario": getpass.getuser(),
        "hostname": hostname,
        "ip": ip,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def print_seal():
    info = audit()
    print(SEAL, file=sys.stderr)
    print(f"  Usuario: {info['usuario']} | Host: {info['hostname']} | IP: {info['ip']}", file=sys.stderr)
