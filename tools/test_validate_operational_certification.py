#!/usr/bin/env python3
import copy
import json
import tempfile
import unittest
from pathlib import Path

from validate_operational_certification import CertificationError, validate


ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "operations/certification-matrix.json"


class CertificationValidatorTests(unittest.TestCase):
    def write_matrix(self, data, directory):
        path = Path(directory) / "matrix.json"
        path.write_text(json.dumps(data))
        return path

    def test_repository_matrix_is_complete(self):
        result = validate(ROOT, MATRIX)
        self.assertTrue(result["valid"])
        self.assertEqual(result["validatedOperationalFloor"], 1999)
        self.assertEqual(result["validatedSessionCount"], 29)
        self.assertEqual(result["goldCertificationDocuments"], 50)
        self.assertEqual(result["unseenValidationDocuments"], 25)

    def test_duplicate_session_key_is_rejected(self):
        data = json.loads(MATRIX.read_text())
        data["sessions"][1]["sessionKey"] = data["sessions"][0]["sessionKey"]
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(CertificationError, "duplicate sessionKey"):
                validate(ROOT, self.write_matrix(data, tmp))

    def test_pending_2026_is_inventoried_without_claiming_validation(self):
        result = validate(ROOT, MATRIX)
        self.assertEqual(result['validatedSessionCount'], 29)
        self.assertEqual(result['pendingSessionCount'], 1)
        self.assertEqual(result['inventorySessionCount'], 30)

    def test_pending_session_cannot_claim_validated_status(self):
        data = json.loads(MATRIX.read_text())
        data['pendingSessions'][0]['status'] = 'validated'
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(CertificationError, 'must not claim validation'):
                validate(ROOT, self.write_matrix(data, tmp))

    def test_duplicate_between_pending_and_validated_is_rejected(self):
        data = json.loads(MATRIX.read_text())
        data['pendingSessions'][0]['sessionKey'] = data['sessions'][0]['sessionKey']
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(CertificationError, 'duplicate sessionKey'):
                validate(ROOT, self.write_matrix(data, tmp))

    def test_pre1999_session_cannot_be_marked_validated(self):
        data = json.loads(MATRIX.read_text())
        extra = copy.deepcopy(data["sessions"][0])
        extra["sessionKey"] = "1997"
        extra["plan"] = "operations/1997-session-plan.json"
        extra["workflow"] = ".github/workflows/full-session-1997.yml"
        data["sessions"].append(extra)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(CertificationError, "predates operational floor"):
                validate(ROOT, self.write_matrix(data, tmp))

    def test_missing_session_entry_is_rejected(self):
        data = json.loads(MATRIX.read_text())
        data["sessions"] = data["sessions"][:-1]
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(CertificationError, "session-plan coverage mismatch"):
                validate(ROOT, self.write_matrix(data, tmp))

    def test_1997_exclusion_cannot_be_rewritten_as_validated(self):
        data = json.loads(MATRIX.read_text())
        data["qualifiedExclusions"][0]["status"] = "validated"
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(CertificationError, "source-availability exclusion"):
                validate(ROOT, self.write_matrix(data, tmp))


if __name__ == "__main__":
    unittest.main()
