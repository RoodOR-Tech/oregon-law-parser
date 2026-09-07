import copy
import unittest

from ors.tools import parse_ors_chapter as parser
from ors.tools import gold_note_validation as gold


class NoteCompletionTests(unittest.TestCase):
    def test_notes_after_future_version_and_form_heading_keep_their_section(self):
        markup = ('<p><b>105.136 Notice.</b> Current. [2025 c.598 §6]</p>'
                  '<p><b>Note:</b> Future version follows.</p>'
                  '<p><b>105.136.</b> (1) Future text.</p><p>NOTICE FORM</p>'
                  '<p>Form contents.</p><p><b>Note:</b> Series membership.</p>'
                  '<p><b>105.137 Trial.</b> Text. [2025 c.598 §2]</p>'
                  '<p>FORM HEADING</p><p><b>Note:</b> Sec. 3. Uncodified law.</p>'
                  '<p>NEW SUBDIVISION</p><p>(New Group)</p>'
                  '<p><b>105.138 Next.</b> Text.</p>')
        sections = {s['sectionNumber']:s for s in parser.parse_chapter(markup,'105')['sections']}
        self.assertEqual([n['text'] for n in sections['105.136']['notes']],
                         ['Note: Future version follows.','Note: Series membership.'])
        self.assertEqual(sections['105.137']['notes'][0]['text'],'Note: Sec. 3. Uncodified law.')
        text,_ = parser.normalize_chapter_text(markup)
        for section in sections.values():
            for note in section['notes']:
                self.assertEqual(text[note['charOffsetStart']:note['charOffsetEnd']],note['text'])

    def test_statutory_form_note_remains_body_text_and_footer_stays_out_of_editorial_note(self):
        markup = ('<p><b>105.464 Form.</b> A. Floodplain?</p>'
                  '<p>Note: Flood insurance may be required.</p><p>B. Other question.</p>'
                  '<p>[2003 c.328 §3]</p><p><b>Note:</b> Editorial text.</p><p>_______________</p>')
        section = parser.parse_chapter(markup,'105')['sections'][0]
        self.assertIn('Note: Flood insurance may be required.',section['bodyText'])
        self.assertIn('B. Other question.',section['bodyText'])
        self.assertEqual(section['notes'][0]['text'],'Note: Editorial text.')
        self.assertEqual(section['sourceCreditRaw'],'[2003 c.328 §3]')


class NoteGoldGateTests(unittest.TestCase):
    def setUp(self):
        self.note = {'sectionId':'2025-12.118','ordinal':1,'noteKind':'editorial_note','noteText':'Note: Test.',
                     'charOffsetStart':10,'charOffsetEnd':21}
        self.selection = {'editionYear':2025,'chapters':[{'chapterNumber':'12'}]}
        source = {'chapterNumber':'12','sha256':'a'*64,'sourceUrl':'https://example.test/ors012.html','bytes':123}
        self.provenance = {'documents':[source]}
        self.review = {'reviewMethod':{'parserNoteOutputConsultedBeforeFreeze':False},'expectedNoteCount':1,
                       'chapters':[{'chapterNumber':'12','sourceSha256':source['sha256'],'sourceUrl':source['sourceUrl'],
                                    'sourceBytes':123,'notes':[dict(self.note)]}]}
        self.rows = {'sectionNotes':[dict(self.note)]}

    def check(self, rows=None, review=None):
        return gold.validate(review or self.review,self.selection,self.provenance,rows or self.rows)

    def test_exact_source_match_passes(self):
        self.assertTrue(self.check()['valid'])

    def test_missing_duplicate_wrong_attachment_and_corrupted_text_fail(self):
        for notes in ([],[self.note,self.note],[dict(self.note,sectionId='2025-12.132')],
                      [dict(self.note,noteText='Note: Bad!!')],[dict(self.note,charOffsetEnd=20)]):
            with self.subTest(notes=notes):
                self.assertFalse(self.check(rows={'sectionNotes':notes})['valid'])

    def test_review_drift_or_missing_chapter_fails(self):
        changed=copy.deepcopy(self.review)
        changed['chapters'][0]['sourceSha256']='b'*64
        self.assertFalse(self.check(review=changed)['valid'])
        changed=copy.deepcopy(self.review)
        changed['chapters']=[]
        self.assertFalse(self.check(review=changed)['valid'])
