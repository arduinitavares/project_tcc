"""Script to delete a project and all its related data from the database.
Usage: python -m scripts.delete_project <product_id> [db_path]
"""

import argparse
import sqlite3
from contextlib import closing
from pathlib import Path

from utils.runtime_config import resolve_database_target


def resolve_db_path(explicit_path: str | None = None) -> str:
    """Resolve a database path from CLI input or required runtime config."""
    return resolve_database_target(
        explicit_path,
        env_name="PROJECT_TCC_DB_URL",
    ).sqlite_connect_target


def delete_project(product_id: int, db_path: str):
    print(f"Connecting to database at: {db_path}")
    if db_path != ":memory:" and not Path(db_path).exists():
        raise FileNotFoundError(f"Database file not found: {db_path}")
    with closing(sqlite3.connect(db_path)) as conn, conn:
        conn.execute("PRAGMA foreign_keys = ON;")
        cur = conn.cursor()
        # Verify project exists
        cur.execute("SELECT name FROM products WHERE product_id=?", (product_id,))
        res = cur.fetchone()
        if not res:
            print(f"Product ID {product_id} not found.")
            return

        print(f"Found product: {res[0]} (ID: {product_id}). preparing to delete...")

        # 1. Collect hierarchical IDs to delete
        # Themes
        cur.execute("SELECT theme_id FROM themes WHERE product_id=?", (product_id,))
        theme_ids = [r[0] for r in cur.fetchall()]

        # Epics
        epic_ids = []
        if theme_ids:
            placeholders = ",".join(["?"] * len(theme_ids))
            cur.execute(
                f"SELECT epic_id FROM epics WHERE theme_id IN ({placeholders})",
                theme_ids,
            )
            epic_ids = [r[0] for r in cur.fetchall()]

        # Features
        feature_ids = []
        if epic_ids:
            placeholders = ",".join(["?"] * len(epic_ids))
            cur.execute(
                f"SELECT feature_id FROM features WHERE epic_id IN ({placeholders})",
                epic_ids,
            )
            feature_ids = [r[0] for r in cur.fetchall()]

        # Sprints
        cur.execute("SELECT sprint_id FROM sprints WHERE product_id=?", (product_id,))
        sprint_ids = [r[0] for r in cur.fetchall()]

        # Spec versions
        cur.execute(
            "SELECT spec_version_id FROM spec_registry WHERE product_id=?",
            (product_id,),
        )
        spec_version_ids = [r[0] for r in cur.fetchall()]

        print(
            "  - Associated records found: "
            f"{len(theme_ids)} themes, "
            f"{len(epic_ids)} epics, "
            f"{len(feature_ids)} features, "
            f"{len(sprint_ids)} sprints, "
            f"{len(spec_version_ids)} spec versions"
        )

        # 2. Delete Dependent Records (Order matters if FKs are restricted, though we set ON)
        # However, manual deletion ensures we don't hit constraints if cascade isn't perfect.

        print(
            "  - Deleting story_completion_logs linked to user stories of this product..."
        )
        cur.execute(
            "DELETE FROM story_completion_logs "
            "WHERE story_id IN (SELECT story_id FROM user_stories WHERE product_id=?)",
            (product_id,),
        )

        print("  - Deleting tasks linked to user stories of this product...")
        cur.execute(
            "DELETE FROM tasks WHERE story_id IN (SELECT story_id FROM user_stories WHERE product_id=?)",
            (product_id,),
        )

        print("  - Deleting sprint_stories linked to user stories of this product...")
        cur.execute(
            "DELETE FROM sprint_stories WHERE story_id IN (SELECT story_id FROM user_stories WHERE product_id=?)",
            (product_id,),
        )
        if sprint_ids:
            placeholders = ",".join(["?"] * len(sprint_ids))
            cur.execute(
                f"DELETE FROM sprint_stories WHERE sprint_id IN ({placeholders})",
                sprint_ids,
            )

        print("  - Deleting user_stories...")
        cur.execute("DELETE FROM user_stories WHERE product_id=?", (product_id,))

        print("  - Deleting workflow_events linked to this product's sprints...")
        if sprint_ids:
            placeholders = ",".join(["?"] * len(sprint_ids))
            cur.execute(
                f"DELETE FROM workflow_events WHERE sprint_id IN ({placeholders})",
                sprint_ids,
            )

        if feature_ids:
            print(f"  - Deleting {len(feature_ids)} features...")
            placeholders = ",".join(["?"] * len(feature_ids))
            cur.execute(
                f"DELETE FROM features WHERE feature_id IN ({placeholders})",
                feature_ids,
            )

        if epic_ids:
            print(f"  - Deleting {len(epic_ids)} epics...")
            placeholders = ",".join(["?"] * len(epic_ids))
            cur.execute(
                f"DELETE FROM epics WHERE epic_id IN ({placeholders})", epic_ids
            )

        if theme_ids:
            print(f"  - Deleting {len(theme_ids)} themes...")
            placeholders = ",".join(["?"] * len(theme_ids))
            cur.execute(
                f"DELETE FROM themes WHERE theme_id IN ({placeholders})", theme_ids
            )

        if sprint_ids:
            print(f"  - Deleting {len(sprint_ids)} sprints...")
            placeholders = ",".join(["?"] * len(sprint_ids))
            cur.execute(
                f"DELETE FROM sprints WHERE sprint_id IN ({placeholders})", sprint_ids
            )

        print("  - Deleting workflow_events...")
        cur.execute("DELETE FROM workflow_events WHERE product_id=?", (product_id,))

        print("  - Deleting product_teams...")
        cur.execute("DELETE FROM product_teams WHERE product_id=?", (product_id,))

        print("  - Deleting product_personas...")
        cur.execute("DELETE FROM product_personas WHERE product_id=?", (product_id,))

        print("  - Deleting spec_authority_acceptance...")
        cur.execute(
            "DELETE FROM spec_authority_acceptance WHERE product_id=?", (product_id,)
        )

        if spec_version_ids:
            print("  - Deleting compiled_spec_authority...")
            placeholders = ",".join(["?"] * len(spec_version_ids))
            cur.execute(
                "DELETE FROM compiled_spec_authority "
                f"WHERE spec_version_id IN ({placeholders})",
                spec_version_ids,
            )

        print("  - Deleting spec_registry...")
        cur.execute("DELETE FROM spec_registry WHERE product_id=?", (product_id,))

        print("  - Deleting product root record...")
        cur.execute("DELETE FROM products WHERE product_id=?", (product_id,))

        conn.commit()
        print("Deletion complete.")

        # Verify
        cur.execute("SELECT count(*) FROM products WHERE product_id=?", (product_id,))
        count = cur.fetchone()[0]
        if count == 0:
            print(f"SUCCESS: Product {product_id} successfully deleted.")
        else:
            print(f"WARNING: Product {product_id} still exists.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Delete a project and all related records from the configured business database.",
    )
    parser.add_argument("product_id", type=int, help="Product ID to delete.")
    parser.add_argument(
        "db",
        nargs="?",
        help="Optional SQLite database path or sqlite:/// URL. Defaults to PROJECT_TCC_DB_URL.",
    )
    args = parser.parse_args()
    delete_project(args.product_id, resolve_db_path(args.db))


if __name__ == "__main__":
    main()
