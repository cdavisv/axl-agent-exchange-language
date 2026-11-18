"""Freeze deterministic held-out synthetic corpus before token measurement."""

import hashlib
import json
from pathlib import Path


def build():
    shapes = {
        "code_logs": [
            ("language", "string"),
            ("source", "string"),
            ("log", "string"),
            ("exit_code", "integer"),
        ],
        "urls": [
            ("method", "string"),
            ("url", "string"),
            ("redirect", "string"),
            ("etag", "string"),
        ],
        "multiline_docs": [("section", "string"), ("body", "string"), ("approved", "boolean")],
        "multilingual_controls": [
            ("locale", "string"),
            ("message", "string"),
            ("empty", "string"),
            ("opaque", "string"),
            ("count", "integer"),
        ],
        "numeric_only": [
            ("epoch", "integer"),
            ("offset", "integer"),
            ("ratio", "number"),
            ("enabled", "boolean"),
            ("missing", "null"),
        ],
        "nested_heavy": [
            ("label", "string"),
            ("tree", "object"),
            ("events", "array"),
            ("extra", "any"),
        ],
    }
    cases = []
    for family, fields in shapes.items():
        for count in (1, 7, 31):
            for share in (False, True):
                turns = []
                for turn in range(16):
                    records = []
                    for row in range(count):
                        i = turn * count + row
                        vals = {
                            "code_logs": [
                                "python",
                                f'def transform_{i}(value):\n    return {{"key": value, "ok": True}}\n',
                                f"WARN item={i} retry={i % 4}\ntrace\\segment\tfinished",
                                i % 3,
                            ],
                            "urls": [
                                "GET",
                                f"https://example.invalid/v2/items/{i}?q=alpha%20beta&sort=desc#part-{i % 5}",
                                f"/cache/{i:06d}/?next=%2Fhome",
                                f'W/"revision-{i}"',
                            ],
                            "multiline_docs": [
                                "appendix",
                                f"## Observation {i}\n\n- Preserve ordered evidence.\n- Verify before changing the plan.\n\n| field | value |\n| run | {i} |\n",
                                i % 2 == 0,
                            ],
                            "multilingual_controls": [
                                "mixed",
                                [
                                    "\u03b4\u03bf\u03ba\u03b9\u03bc\u03ae \u041f\u0440\u0438\u0432\u0435\u0442",
                                    "\u0939\u093f\u0928\u094d\u0926\u0940 \u0e44\u0e17\u0e22",
                                    "\ud55c\uad6d\uc5b4 e\u0301 \U0001f680",
                                    "\x01\x02\x0b\x1f\t\n\r",
                                ][i % 4],
                                "",
                                ["", "  ", "\u2028\u2029", "\\x01"][i % 4],
                                i,
                            ],
                            "numeric_only": [1700000000, i - 80, i / 13.0, i % 2 == 1, None],
                            "nested_heavy": [
                                "graph",
                                {
                                    "root": i,
                                    "children": [
                                        {
                                            "id": j,
                                            "weights": [j / 7.0, None, False],
                                            "meta": {"name": f"leaf-{i}-{j}", "quoted": '"inner"'},
                                        }
                                        for j in range(3)
                                    ],
                                },
                                [
                                    {"step": j, "values": [i + j, str(i + j), True]}
                                    for j in range(4)
                                ],
                                {"optional": [None, {"literal": "001", "path": "a\\b"}]},
                            ],
                        }[family]
                        records.append(dict(zip((f[0] for f in fields), vals)))
                    turns.append(records)
                cases.append(
                    {
                        "family": family,
                        "fields": fields,
                        "rows": count,
                        "shared": [fields[0][0]] if share else [],
                        "turns": turns,
                    }
                )
    cases.append(
        {
            "family": "empty_batches",
            "fields": [("text", "string")],
            "rows": 0,
            "shared": [],
            "turns": [[] for _ in range(16)],
        }
    )
    cases.append(
        {
            "family": "all_shared",
            "fields": [("text", "string")],
            "rows": 7,
            "shared": ["text"],
            "turns": [[{"text": "constant empty-safe value"} for _ in range(7)] for _ in range(16)],
        }
    )
    return {
        "design": "Frozen before token results; 6 new strata/schema shapes, 1/7/31 rows, first-field sharing on/off, 16 turns. No private data. All fields required.",
        "cases": cases,
    }


if __name__ == "__main__":
    p = Path(__file__).with_name("heldout-corpus.json")
    if p.exists():
        raise SystemExit("Refusing to replace frozen corpus")
    raw = (json.dumps(build(), ensure_ascii=True, separators=(",", ":")) + "\n").encode()
    p.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    p.with_name("heldout-corpus.sha256").write_text(digest + "\n", encoding="ascii")
    print(digest)
