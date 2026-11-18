"""Freeze newly authored synthetic semantic corpus before measurements."""

import hashlib
import json
from pathlib import Path


def build():
    cases = []
    families = {
        "study": ("default_heavy", "enum_varied", "presence_mixed"),
        "holdout": ("short_codes", "unmapped_payload", "numeric_types"),
    }
    for split, names in families.items():
        for family in names:
            table = (
                ["queued_for_validation", "running_with_dependencies", "completed_successfully"]
                if split == "study"
                else ["A", "B", "C", "D"]
            )
            for count in (1, 7, 31):
                turns = []
                for turn in range(16):
                    records = []
                    for row in range(count):
                        i = count * turn + row
                        item = {
                            "status": table[(i % len(table)) if family != "default_heavy" else 0]
                        }
                        if family == "default_heavy":
                            item.update(attempts=0, note="", payload=None)
                        elif family == "enum_varied":
                            item.update(attempts=i % 3, note="", payload=None)
                        elif family == "presence_mixed":
                            if i % 3:
                                item["attempts"] = [0, 0.0, -0.0][i % 3]
                            if i % 4:
                                item["note"] = "" if i % 2 else "keep exact whitespace  "
                            if i % 2:
                                item["payload"] = None
                        elif family == "short_codes":
                            item.update(
                                attempts=i,
                                note=f"https://example.invalid/items/{i}?flag=yes",
                                payload={"a": i, "b": [False, "0"]},
                            )
                        elif family == "unmapped_payload":
                            item.update(
                                attempts=0,
                                note=f'def stage_{i}():\n    return "ok"\n',
                                payload={
                                    "events": [
                                        {
                                            "step": j,
                                            "text": f"event-{i}-{j}",
                                            "items": [None, True, j / 3],
                                        }
                                        for j in range(3)
                                    ]
                                },
                            )
                        else:
                            if i % 5:
                                item["attempts"] = [0, 0.0, -0.0, 1, 1.0][i % 5]
                            if i % 3:
                                item["note"] = ""
                            if i % 4:
                                item["payload"] = [None, False, 0, 0.0][i % 4]
                        records.append(item)
                    turns.append(records)
                cases.append(
                    {
                        "split": split,
                        "family": family,
                        "rows": count,
                        "enums": table,
                        "turns": turns,
                    }
                )
    return {
        "design": "New deterministic synthetic study and holdout authored together and frozen before any measurement; unchanged mapping across both. Not naturalistic/task success evidence.",
        "cases": cases,
    }


if __name__ == "__main__":
    p = Path(__file__).with_name("corpus.json")
    if p.exists():
        raise SystemExit("Refusing to replace frozen corpus")
    raw = (json.dumps(build(), ensure_ascii=True, separators=(",", ":")) + "\n").encode()
    p.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    p.with_name("corpus.sha256").write_text(digest + "\n", encoding="ascii")
    print(digest)
