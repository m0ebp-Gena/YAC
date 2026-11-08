"""Message and distance filters for FT8/FT4 receive history."""

from math import asin, cos, isfinite, radians, sin, sqrt
import re


KM_PER_MILE = 1.609344
GRID = re.compile(r'[A-R]{2}[0-9]{2}(?:[A-X]{2})?')
CALL = re.compile(r'(?=[A-Z0-9/]*[0-9])(?=[A-Z0-9/]*[A-Z])[A-Z0-9/]+')


def grid_center(locator):
    locator = locator.upper()
    if not GRID.fullmatch(locator):
        return None
    lon = (ord(locator[0]) - ord('A')) * 20 + int(locator[2]) * 2 - 180
    lat = (ord(locator[1]) - ord('A')) * 10 + int(locator[3]) - 90
    if len(locator) == 6:
        lon += (ord(locator[4]) - ord('A') + 0.5) / 12
        lat += (ord(locator[5]) - ord('A') + 0.5) / 24
    else:
        lon += 1
        lat += 0.5
    return radians(lat), radians(lon)


def message_distance(message, origin):
    words = message.upper().split()
    if origin is None or len(words) < 3 or words[-1] == 'RR73':
        return None
    # In an acknowledged grid exchange, the R precedes the locator.
    sender = words[-3 if words[-2] == 'R' else -2].strip('<>')
    if sender != '...' and not CALL.fullmatch(sender):
        return None
    destination = grid_center(words[-1])
    if destination is None:
        return None
    lat, lon = origin
    other_lat, other_lon = destination
    hav = sin((other_lat - lat) / 2)**2 + cos(lat) * cos(other_lat) * sin((other_lon - lon) / 2)**2
    return 2 * 6371.0088 * asin(min(1, sqrt(hav)))


def distance_settings(settings):
    limit = float(settings.get('ft_distance', '2000'))
    unit = settings.get('ft_distance_unit', 'km').casefold()
    if unit == 'miles':
        unit = 'mi'
    if not isfinite(limit) or limit <= 0 or unit not in ('km', 'mi'):
        raise ValueError('Invalid FT distance setting')
    return limit, unit
