#!/usr/bin/env python3
"""Offline YAML syntax validator for k8s/ manifests."""
import yaml, glob, sys

errors = []
docs_total = 0
files = sorted(glob.glob("k8s/*.yaml"))

for path in files:
    with open(path) as f:
        raw = f.read()
    try:
        docs = [d for d in yaml.safe_load_all(raw) if d]
        docs_total += len(docs)
        kinds = ", ".join(d.get("kind", "?") for d in docs)
        print("  OK  {:45s} ({} doc(s): {})".format(path, len(docs), kinds))
    except yaml.YAMLError as exc:
        errors.append((path, str(exc)))
        print("FAIL  {}: {}".format(path, exc))

print("\nTotal: {} resources across {} files".format(docs_total, len(files)))
if errors:
    print("{} YAML error(s) found!".format(len(errors)))
    sys.exit(1)
else:
    print("All YAML files are syntactically valid.")
