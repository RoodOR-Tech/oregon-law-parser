import copy
import unittest
from ors.tools.validate_gold_parse import validate


class GoldParseValidationTests(unittest.TestCase):
    def setUp(self):
        self.selection = {"chapters": [{"chapterNumber": "471"}]}
        self.report = {
            "problems": [], "integrityViolations": [], "unreadable": [],
            "chaptersWithoutName": [], "unreadableChapterCount": 0,
            "editorialNoteCandidateCount": 0, "parsedChapterCount": 1,
            "perChapter": [{"chapterNumber": "471"}], "sectionRowCount": 271,
            "unparsedCreditSegments": [],
            "unparsedCreditSegmentCount": 0, "valid": True,
        }

    def test_no_credit_gap_is_allowed(self):
        self.assertEqual(validate(self.report, self.selection, 0), [])
        self.report['unparsedCreditSegments'] = [{'sectionId': '2025-471.410', 'segments': ['1983 cor. c.736 §1']}]
        self.report['unparsedCreditSegmentCount'] = 1
        self.report['valid'] = False
        self.assertTrue(validate(self.report, self.selection, 1))

    def test_other_parser_failures_are_never_masked(self):
        for field, value in [("problems", ["bad edition"]),
                             ("integrityViolations", ["duplicate"]),
                             ("editorialNoteCandidateCount", 1),
                             ("chaptersWithoutName", ["471"]),
                             ("perChapter", []), ("unreadableChapterCount", 1)]:
            with self.subTest(field=field):
                report = copy.deepcopy(self.report)
                report[field] = value
                self.assertTrue(validate(report, self.selection, 0))
        self.assertTrue(validate(self.report, self.selection, 2))

    def test_fixing_known_gaps_is_allowed(self):
        self.report.update(unparsedCreditSegments=[], unparsedCreditSegmentCount=0, valid=True)
        self.assertEqual(validate(self.report, self.selection, 0), [])
