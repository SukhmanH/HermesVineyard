#!/usr/bin/env python3
"""Export the local dashboard as a static, deployable site.

Produces a directory that is pure HTML/CSS/JS + one JSON snapshot, with no
server and no database. Safe to host anywhere static (Vercel, Cloudflare Pages).

The live panel's frontend fetches /api/dashboard from the Python server. Here we
write that payload to dashboard.json and rewrite ONLY the exported copy of
dashboard.js to read it. Source files are never modified.

Usage:
    python tools/build_panel_static.py [--out data/exports/panel]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vineyard_mcp.dashboard import build_dashboard  # noqa: E402

SRC = Path(__file__).resolve().parent.parent / "vineyard_mcp"
ASSETS = ("dashboard.html", "dashboard.css", "dashboard.js")

# Sections that are commercially or personally sensitive. Excluded unless
# --include-sensitive is passed explicitly.
SENSITIVE = {"listings", "crew"}


def build(out_dir: Path, *, include_sensitive: bool = False) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)

    snapshot = build_dashboard()

    dropped = []
    if not include_sensitive:
        kept = []
        for section in snapshot.get("sections", []):
            if section.get("id") in SENSITIVE:
                dropped.append(section.get("id"))
                continue
            kept.append(section)
        snapshot["sections"] = kept

    snapshot["export_generated_at"] = datetime.now(UTC).isoformat()
    snapshot["export_is_static"] = True

    (out_dir / "dashboard.json").write_text(
        json.dumps(snapshot, ensure_ascii=False, allow_nan=False),
        encoding="utf-8",
    )

    for name in ASSETS:
        text = (SRC / name).read_text(encoding="utf-8")
        if name == "dashboard.js":
            # Point the frontend at the static snapshot instead of the live API.
            if '"/api/dashboard"' not in text:
                raise SystemExit(
                    "dashboard.js no longer fetches /api/dashboard - "
                    "update build_panel_static.py before trusting this export."
                )
            text = text.replace('"/api/dashboard"', '"./dashboard.json"')
            # A static snapshot never changes; stop the 60s refresh loop.
            text = text.replace(
                "setInterval(() => { if (!document.hidden) refresh(); }, 60000);",
                "// static export: auto-refresh disabled",
            )
        target = "index.html" if name == "dashboard.html" else name
        (out_dir / target).write_text(text, encoding="utf-8")

    # index.html references /dashboard.css and /dashboard.js at the root.
    index = out_dir / "index.html"
    index.write_text(
        index.read_text(encoding="utf-8")
        .replace('href="/dashboard.css"', 'href="./dashboard.css"')
        .replace('src="/dashboard.js"', 'src="./dashboard.js"'),
        encoding="utf-8",
    )

    # Deploy config so `vercel deploy --prod` needs no dashboard settings.
    # Compliance data must never be cached by a CDN edge or indexed.
    (out_dir / "vercel.json").write_text(
        json.dumps(
            {
                "$schema": "https://openapi.vercel.sh/vercel.json",
                "headers": [
                    {
                        "source": "/(.*)",
                        "headers": [
                            {"key": "Cache-Control", "value": "no-store, max-age=0"},
                            {"key": "X-Robots-Tag", "value": "noindex, nofollow"},
                            {"key": "X-Content-Type-Options", "value": "nosniff"},
                            {"key": "Referrer-Policy", "value": "no-referrer"},
                            {"key": "X-Frame-Options", "value": "DENY"},
                        ],
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    # Belt and braces: this folder is a deploy root, never a git subtree.
    (out_dir / ".vercelignore").write_text("*.db\n*.db-wal\n*.db-shm\n.env\n", encoding="utf-8")

    return {
        "out": str(out_dir),
        "sections": len(snapshot["sections"]),
        "dropped": dropped,
        "bytes": sum(f.stat().st_size for f in out_dir.iterdir() if f.is_file()),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="data/exports/panel")
    parser.add_argument(
        "--include-sensitive",
        action="store_true",
        help="Include crew names and property listings in the export.",
    )
    args = parser.parse_args()

    result = build(Path(args.out).resolve(), include_sensitive=args.include_sensitive)
    print(f"Static panel written to {result['out']}")
    print(f"  sections : {result['sections']}")
    print(f"  size     : {result['bytes'] / 1024:.0f} KB")
    if result["dropped"]:
        print(f"  EXCLUDED : {', '.join(result['dropped'])} (use --include-sensitive to keep)")


if __name__ == "__main__":
    main()
