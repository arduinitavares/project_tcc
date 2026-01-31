"""CLI for generating project snapshot HTML exports."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

from sqlalchemy.engine import Engine

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.append(str(REPO_ROOT))

from tools.export_snapshot import export_project_snapshot_html


def export_snapshot_command(
    *,
    product_id: int,
    output_dir: Path,
    engine_override: Optional[Engine] = None,
) -> Path:
    """Generate a snapshot HTML file for a product.

    Args:
        product_id: Product identifier.
        output_dir: Destination folder for export.
        engine_override: Optional SQLAlchemy engine for testing.

    Returns:
        Path to the generated HTML file.
    """

    return export_project_snapshot_html(
        product_id=product_id,
        output_dir=output_dir,
        engine_override=engine_override,
    )


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Export project snapshot HTML")
    parser.add_argument("--product-id", type=int, required=True, help="Product ID")
    parser.add_argument(
        "--output-dir",
        type=str,
        default=str(Path("artifacts") / "exports"),
        help="Output folder for snapshot HTML",
    )
    args = parser.parse_args(argv)

    output_path = export_snapshot_command(
        product_id=args.product_id,
        output_dir=Path(args.output_dir),
    )
    print(f"Snapshot written: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())