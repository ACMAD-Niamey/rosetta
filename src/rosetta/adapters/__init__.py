from .cds import CDSAdapter
from .opendap import OPeNDAPAdapter
from .http import HTTPAdapter
from .iridl import IRIDLAdapter
from .mars import MARSAdapter
from .ncei import NCEIAdapter
from .s3 import S3Adapter
from .sheerwater import SheerwaterAdapter
from .ccsr import CCSRAdapter

_ADAPTERS = {
    "cds": CDSAdapter,
    "opendap": OPeNDAPAdapter,
    "http": HTTPAdapter,
    "iridl": IRIDLAdapter,
    "mars": MARSAdapter,
    "ncei": NCEIAdapter,
    "s3": S3Adapter,
    "sheerwater": SheerwaterAdapter,
    "ccsr": CCSRAdapter,
}


def get_adapter(name):
    if name not in _ADAPTERS:
        raise KeyError(f"Unknown adapter: {name}")
    return _ADAPTERS[name]()
