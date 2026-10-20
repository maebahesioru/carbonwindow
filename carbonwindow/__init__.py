"""CarbonWindow — schedule compute jobs into the low-carbon hours of the grid.

The only data source is the free, key-less UK National Grid ESO Carbon Intensity
API (https://api.carbonintensity.org.uk). Nothing in this package invents a number:
every figure the report prints comes from a JSON snapshot written to ``data/``.

Modules
-------
ci_api    HTTP access, 14-day chunking, on-disk cache, normalisation to intervals
optimize  strict O(n) minimum-mean window, plus a brute-force reference
report    reduction rates over a historical window (oracle and forecast-driven)
web       static single-file HTML report with inline SVG charts
cli       ``fetch`` / ``optimize`` / ``report`` / ``web`` entry points
"""

__version__ = "1.0.0"
