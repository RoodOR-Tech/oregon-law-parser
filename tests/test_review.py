from parser.amendments import parse_session
from parser.extract import html_document
from parser.review import classify


def parse(body):
    return parse_session(html_document('<p>OREGON LAWS 2023 Chap. 1</p><p>HB 1001</p>' + body), 'fixture', 2023)


def test_conditional_replacement_preserves_condition_and_only_direct_target():
    result = parse('<p>SECTION 1a. If Senate Bill 308 becomes law, section 1 of this 2023 Act '
                   '(amending ORS 114.535) is repealed and ORS 114.535, as amended by section 13, '
                   'chapter 17, Oregon Laws 2023, is amended to read:</p><p>114.535. Old <b>new</b> text.</p>')
    action, = result['actions']
    assert (action['action_type'], action['affected_ors_section']) == ('AMEND', '114.535')
    assert action['condition_text'] == 'If Senate Bill 308 becomes law'
    assert 'is repealed and ORS' in action['operative_text']
    assert action['raw_diff_text'].strip() == '114.535. Old new text.'
    assert all(action['raw_diff_text'][t['start']:t['end']] == t['text'] for t in action['tokens'])


def test_conditional_act_section_is_not_incidental_ors_action():
    result = parse('<p>SECTION 1. If House Bill 2001 becomes law, section 2 of this 2023 Act '
                   'is amended to read: Sec. 2. The amendments to ORS 161.005 apply next year.</p>')
    assert result['actions'] == []
    assert classify(result['diagnostics'][0])['category'] == 'session_law_provision'


def test_numbered_repeal_retains_remaining_evidence():
    result = parse('<p>SECTION 32. (1) ORS 441.157 is repealed. '
                   '(2) Section 15 of this 2023 Act is repealed on June 2, 2024.</p>')
    assert [a['affected_ors_section'] for a in result['actions']] == ['441.157']
    assert result['diagnostics'][0]['text'].startswith('(2) Section 15')


def test_unknown_and_mixed_targets_stay_open():
    for text in ['Notwithstanding other law, ORS 161.005 is repealed.',
                 'Section 1 of this Act and ORS 161.005 are repealed.']:
        assert classify(dict(reason='unsupported', text=text))['disposition'] == 'review_required'


def test_notwithstanding_conditional_repeal_preserves_full_qualification():
    result = parse('<p>SECTION 8a. Notwithstanding section 8, chapter 202, Oregon Laws 2023 '
                   '(Enrolled Senate Bill 992) (amending ORS 343.161), if Senate Bill 992 becomes law, '
                   'ORS 343.161 is repealed by section 8 of this 2023 Act.</p>')
    action, = result['actions']
    assert action['action_type'] == 'REPEAL'
    assert action['affected_ors_section'] == '343.161'
    assert action['condition_text'].startswith('Notwithstanding section 8')
    assert 'if Senate Bill 992 becomes law' in action['condition_text']


def test_incidental_repeal_does_not_create_an_action():
    text = ('Notwithstanding the transfer of duties, functions and powers by section 2 of this Act, '
            'the rules continue in effect until superseded or repealed by rules of the department.')
    result = parse('<p>SECTION 7. '+text+'</p>')
    assert not result['actions']
    assert classify(result['diagnostics'][0])['category'] == 'incidental_repeal_reference'
