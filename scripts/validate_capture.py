#!/usr/bin/env python3
import json
import sys
from pathlib import Path

p = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("execution_knowledge")
if p.is_dir():
    print("Pass a file path to validate")
    sys.exit(2)

good = 0
bad = 0
req = ["run_id", "started_at", "workspace"]
out_lines = []
for i, line in enumerate(open(p, encoding="utf-8"), 1):
    try:
        obj = json.loads(line)
        if not all(obj.get(x) for x in req):
            print("Missing required fields line", i)
            bad += 1
            continue
        if not obj.get("schema_version"):
            obj["schema_version"] = "v1"
        out_lines.append(json.dumps(obj, ensure_ascii=False))
        good += 1
    except Exception as e:
        print("Invalid JSON line", i, e)
        bad += 1

print("Valid:", good, "Invalid:", bad)
# optional: overwrite validated file
with open(p, "w", encoding="utf-8") as h:
    for line in out_lines:
        h.write(line + "\n")
