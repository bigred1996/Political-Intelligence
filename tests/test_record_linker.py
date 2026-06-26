from pipeline.record_linker import (
    bill_mentions,
    extract_commons_member_id,
    parse_hansard_speaker_name,
    parse_vote_participants_xml,
)


def test_extract_commons_member_id_from_profile_url():
    assert extract_commons_member_id("https://www.ourcommons.ca/members/en/jane-doe(12345)") == "12345"
    assert extract_commons_member_id("/politicians/jane-doe/") is None


def test_bill_mentions_normalizes_house_and_senate_numbers():
    text = "Debate resumed on Bill C-69, plus Bill S-4 and bill c 5."
    assert bill_mentions(text) == {"C-69", "S-4", "C-5"}


def test_parse_vote_participants_xml_extracts_member_vote_context():
    xml = b"""
    <ArrayOfVoteParticipant>
      <VoteParticipant>
        <PersonOfficialFirstName>Jane</PersonOfficialFirstName>
        <PersonOfficialLastName>Doe</PersonOfficialLastName>
        <VoteValueName>Yea</VoteValueName>
        <CaucusShortName>Liberal</CaucusShortName>
        <ConstituencyName>Ottawa Centre</ConstituencyName>
        <PersonId>12345</PersonId>
      </VoteParticipant>
    </ArrayOfVoteParticipant>
    """
    assert parse_vote_participants_xml(xml) == [{
        "person_id": "12345",
        "vote": "Yea",
        "name": "Jane Doe",
        "party": "Liberal",
        "riding": "Ottawa Centre",
    }]



def test_parse_hansard_speaker_name_handles_roles_and_titles():
    assert parse_hansard_speaker_name("Hon. Kevin Lamoureux (Parliamentary Secretary, Lib.)") == "Kevin Lamoureux"
    assert parse_hansard_speaker_name("The Assistant Deputy Speaker (Alexandra Mendès)") == "Alexandra Mendès"
    assert parse_hansard_speaker_name("The Speaker") is None
