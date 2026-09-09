"""Build deterministic histories for explicitly reviewed amendment plans."""
import argparse
import copy
from datetime import date
import json
from pathlib import Path

from build_amendment_preview import build_preview, render_markdown, require, row_digest


def build_batch(entries, verification, as_of):
    cutoff = date.fromisoformat(as_of)
    nodes, bases, children, roots = {}, {}, {}, {}
    for entry in entries:
        base, plan = entry["base"], entry["plan"]
        identifier, section = plan["previewId"], plan["baseSectionId"]
        require(identifier not in nodes, "duplicate preview ID")
        require(base["section"]["section_id"] == section, "base section identity mismatch")
        if section in bases:
            require(base == bases[section], "inconsistent original base for section")
        bases[section] = copy.deepcopy(base)
        parent = plan.get("predecessorPreviewId")
        if parent is None:
            require(section not in roots, "multiple unordered plans for same section")
            roots[section] = identifier
        else:
            require(parent not in children, "branched amendment history requires separate review")
            children[parent] = identifier
        nodes[identifier] = (base, plan)
    for identifier, (_, plan) in nodes.items():
        parent = plan.get("predecessorPreviewId")
        if parent is not None:
            require(parent in nodes, "missing predecessor")
            previous = nodes[parent][1]
            require(previous["baseSectionId"] == plan["baseSectionId"], "predecessor belongs to another section")
            require(date.fromisoformat(previous["operativeDate"]) <= date.fromisoformat(plan["operativeDate"]),
                    "successor operative date precedes predecessor")
    remaining, ordered, visited = set(nodes), [], set()
    while remaining:
        ready = [i for i in remaining if nodes[i][1].get("predecessorPreviewId") in visited
                 or nodes[i][1].get("predecessorPreviewId") is None]
        require(bool(ready), "cyclic amendment history")
        identifier = min(ready, key=lambda i: (date.fromisoformat(nodes[i][1]["operativeDate"]), i))
        ordered.append(identifier)
        visited.add(identifier)
        remaining.remove(identifier)
    previews, pending, generated, current = [], [], {}, {}
    for identifier in ordered:
        original, plan = nodes[identifier]
        if date.fromisoformat(plan["operativeDate"]) > cutoff:
            pending.append(identifier)
            continue
        base = copy.deepcopy(original)
        parent = plan.get("predecessorPreviewId")
        if parent is not None:
            require(parent in generated, "predecessor is not operative")
            base["section"]["body_text"] = generated[parent]["proposedBodyText"]
        # The successor's frozen baseRowSha256 must match this exact derived
        # predecessor. Never recompute or silently refresh the reviewed hash.
        preview = build_preview(base, plan, verification, as_of)
        preview["predecessorPreviewId"] = parent
        previews.append(preview)
        generated[identifier] = preview
        current[plan["baseSectionId"]] = identifier
    return {"schemaVersion": 1, "asOf": as_of,
            "scope": "Explicitly reviewed plan histories only; not an official edition or complete amendment coverage.",
            "planCount": len(nodes), "previewCount": len(previews), "pendingCount": len(pending),
            "pendingPreviewIds": pending, "originalBases": [bases[k] for k in sorted(bases)],
            "currentPreviewBySection": dict(sorted(current.items())), "previews": previews}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--verification", required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    read = lambda p: json.loads(Path(p).read_text(encoding="utf-8"))
    manifest_path = Path(args.manifest)
    manifest = read(manifest_path)
    require(manifest.get("schemaVersion") == 1, "unsupported batch schema")
    entries = [{"base": read(manifest_path.parent / e["base"]),
                "plan": read(manifest_path.parent / e["plan"])} for e in manifest["entries"]]
    report = build_batch(entries, read(args.verification), args.as_of)
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    (output / "batch.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for i, preview in enumerate(report["previews"], 1):
        (output / f"preview-{i}.md").write_text(render_markdown(preview), encoding="utf-8")
    print(json.dumps({"amendmentPreviewBatch": report}))


if __name__ == "__main__":
    main()
