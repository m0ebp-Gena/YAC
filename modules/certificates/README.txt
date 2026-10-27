Mozilla root certificates supplied by certifi 2026.10.23.
Source: https://pypi.org/project/certifi/2026.10.23/
Wheel SHA-256: e9b54de76e530bb6cf0ccd036787103acb58fd42ba930ea8bf948ddbaa2f61d1
See LICENSE.txt for the Mozilla Public License 2.0.

The Mac installer copies this bundle with the modules directory and checks
that it can be loaded. The Windows build includes it in the frozen runtime
and checks that it loads. Both updaters add it to Python's trusted roots
for all update requests, including release lookup, checksums and downloads.
Linux retains its existing HTTPS certificate handling.

Refresh this bundle from a verified certifi release when preparing releases.
