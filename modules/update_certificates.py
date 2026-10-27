"""Verified HTTPS using system trust plus YAC's bundled Mozilla roots."""
from pathlib import Path
import ssl


def context():
    # Keep system trust where available and add the shipped Mozilla root bundle.
    # Never fall back to an unverified connection if the bundle is missing/broken.
    result = ssl.create_default_context()
    result.load_verify_locations(cafile=str(Path(__file__).with_name('certificates') / 'cacert.pem'))
    return result
