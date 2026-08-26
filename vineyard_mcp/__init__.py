"""vineyard_mcp — the compliance kernel.

The only code in this project. Everything else the vineyard assistant does — fetching weather,
reading the listings inbox, building workbooks, composing reports — Hermes does itself with
execute_code (docs/01 §D9).

What lives here is the narrow set that must be true regardless of which model is running, on a
bad day, mid-outage, or under a prompt-injected message: the append-only record, the four
obligations, and a spray verdict that fails safe.
"""

__version__ = "0.1.0"
