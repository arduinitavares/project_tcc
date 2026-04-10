import json
import sys
from pathlib import Path

from sqlmodel import Session, select

REPO_ROOT = Path().resolve()
if str(REPO_ROOT) not in sys.path:
    sys.path.append(str(REPO_ROOT))

from agile_sqlmodel import UserStory, get_engine


def check_failure_reasons():
    engine = get_engine()
    print(f"Engine URL: {engine.url}")
    with Session(engine) as session:
        stories = session.exec(select(UserStory)).all()

    reasons = {}
    for s in stories:
        if s.validation_evidence:
            try:
                ev = json.loads(s.validation_evidence)
                if not ev.get("passed"):
                    for f in ev.get("failures", []):
                        rule = f.get("rule")
                        reasons[rule] = reasons.get(rule, 0) + 1
            except:
                pass

    print("Failure Reasons in DB:")
    for r, c in reasons.items():
        print(f"  {r}: {c}")


if __name__ == "__main__":
    check_failure_reasons()
