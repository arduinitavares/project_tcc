import sqlite3

DB_PATH = "c:/Users/mjnrc/projects/project_tcc/db/spec_authority_dev.db"

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

tables = [r[0] for r in cur.execute("select name from sqlite_master where type='table' order by name")]
print("tables:", tables)

for t in ["feature", "features", "Feature", "featureforstory", "theme", "themes", "Theme", "epic", "epics", "Epic"]:
    if t in tables:
        cols = cur.execute(f"pragma table_info({t})").fetchall()
        print("\n", t, cols)

conn.close()

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

feature_id = 93
feature_row = cur.execute(
    "select feature_id, title, epic_id from features where feature_id=?",
    (feature_id,),
).fetchone()
print("\nfeature:", feature_row)

theme_row = None
if feature_row:
    epic_id = feature_row[2]
    epic_row = cur.execute(
        "select epic_id, title, theme_id from epics where epic_id=?",
        (epic_id,),
    ).fetchone()
    print("epic:", epic_row)
    if epic_row:
        theme_id = epic_row[2]
        theme_row = cur.execute(
            "select theme_id, title, time_frame, description from themes where theme_id=?",
            (theme_id,),
        ).fetchone()
        print("theme:", theme_row)

conn.close()
