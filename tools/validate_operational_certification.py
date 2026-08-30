#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path


class CertificationError(ValueError):
    pass


def load_json(path: Path):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError as exc:
        raise CertificationError(f"missing required file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise CertificationError(f"invalid JSON in {path}: {exc}") from exc


def require(condition, message):
    if not condition:
        raise CertificationError(message)


def validate(root: Path, matrix_path: Path):
    matrix = load_json(matrix_path)
    require(matrix.get("schemaVersion") == 1, "certification matrix schemaVersion must be 1")
    floor = matrix.get("validatedOperationalFloor")
    require(floor == 1999, f"validated operational floor must remain 1999, got {floor!r}")

    benchmarks = matrix.get("frozenBenchmarks", {})
    require(benchmarks.get("goldCertificationDocuments") == 50,
            "frozen gold certification count must remain 50")
    require(benchmarks.get("unseenValidationDocuments") == 25,
            "frozen unseen validation count must remain 25")

    exclusions = matrix.get("qualifiedExclusions", [])
    require(len(exclusions) == 1, "matrix must contain exactly the established 1997 qualified exclusion")
    exclusion = exclusions[0]
    require(exclusion.get("sessionKey") == "1997", "qualified exclusion must identify 1997")
    require(exclusion.get("status") == "not-validated-source-unavailable-online",
            "1997 must remain a source-availability exclusion, not a validated session")
    evidence_rel = exclusion.get("evidence")
    require(evidence_rel == "operations/pre-1999-source-boundary.json",
            "1997 exclusion must reference the permanent source-boundary record")
    boundary = load_json(root / evidence_rel)
    require(boundary.get("validatedOperationalFloor") == floor,
            "source-boundary floor disagrees with certification matrix")
    excluded = boundary.get("excludedSession", {})
    require(excluded.get("year") == 1997, "source-boundary record must describe 1997")
    require(excluded.get("status") == exclusion.get("status"),
            "1997 exclusion status disagrees with source-boundary record")
    require(excluded.get("acquiredDocuments") == 0 and excluded.get("parsedDocuments") == 0,
            "1997 qualified exclusion must not be rewritten as acquired or parsed coverage")

    sessions = matrix.get("sessions", [])
    require(sessions, "certification matrix contains no validated sessions")
    keys = [item.get("sessionKey") for item in sessions]
    plans = [item.get("plan") for item in sessions]
    workflows = [item.get("workflow") for item in sessions]
    require(None not in keys + plans + workflows, "every session needs sessionKey, plan, and workflow")
    require(len(keys) == len(set(keys)), "duplicate sessionKey in certification matrix")
    require(len(plans) == len(set(plans)), "duplicate session plan in certification matrix")
    require(len(workflows) == len(set(workflows)), "duplicate session workflow in certification matrix")

    for item in sessions:
        require(item.get("status") == "validated", f"{item.get('sessionKey')}: session is not marked validated")
        key = item["sessionKey"]
        try:
            year = int(key[:4])
        except (TypeError, ValueError) as exc:
            raise CertificationError(f"invalid sessionKey year prefix: {key!r}") from exc
        require(year >= floor, f"{key}: validated session predates operational floor {floor}")
        require((root / item["plan"]).is_file(), f"{key}: missing session plan {item['plan']}")
        require((root / item["workflow"]).is_file(), f"{key}: missing workflow {item['workflow']}")

    repo_plans = {str(path.relative_to(root)) for path in (root / "operations").glob("*-session-plan.json")}
    repo_workflows = {str(path.relative_to(root)) for path in (root / ".github/workflows").glob("full-session-*.yml")}
    matrix_plans = set(plans)
    matrix_workflows = set(workflows)
    require(matrix_plans == repo_plans,
            f"session-plan coverage mismatch; missing={sorted(repo_plans - matrix_plans)}, extra={sorted(matrix_plans - repo_plans)}")
    require(matrix_workflows == repo_workflows,
            f"workflow coverage mismatch; missing={sorted(repo_workflows - matrix_workflows)}, extra={sorted(matrix_workflows - repo_workflows)}")

    gold = load_json(root / "gold/manifest.json")
    gold_docs = gold.get("documents", [])
    require(gold.get("releaseCertificationMinimumDocuments") == 50,
            "gold manifest release-certification minimum changed from 50")
    require(len(gold_docs) == 50, f"frozen gold manifest must contain exactly 50 documents, got {len(gold_docs)}")

    unseen = load_json(root / "validation/pending/unseen-25-candidates.json")
    unseen_docs = unseen.get("documents", [])
    require(len(unseen_docs) == 25, f"frozen unseen selection must contain exactly 25 documents, got {len(unseen_docs)}")
    unseen_ids = [item.get("id") for item in unseen_docs]
    require(len(set(unseen_ids)) == 25, "frozen unseen selection contains duplicate IDs")

    hashes = load_json(root / "validation/reviews/unseen-25-source-hashes.json")
    hash_docs = hashes.get("documents", [])
    hash_ids = [item.get("id") for item in hash_docs]
    require(hashes.get("valid") is True, "unseen source-hash registry is not valid")
    require(len(hash_docs) == 25 and set(hash_ids) == set(unseen_ids),
            "unseen source-hash registry no longer exactly covers the frozen 25-law selection")

    return {
        "valid": True,
        "validatedOperationalFloor": floor,
        "validatedSessionCount": len(sessions),
        "qualifiedExclusionCount": len(exclusions),
        "goldCertificationDocuments": len(gold_docs),
        "unseenValidationDocuments": len(unseen_docs),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--matrix", default="operations/certification-matrix.json")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    matrix_path = Path(args.matrix)
    if not matrix_path.is_absolute():
        matrix_path = root / matrix_path
    try:
        result = validate(root, matrix_path)
    except CertificationError as exc:
        print(f"operational certification error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
