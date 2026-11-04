"""Redaction checks, including formats that do NOT appear in the dataset
(so the dataset score isn't the only evidence). Known gaps are marked xfail
and listed in the README; they are honest limitations, not hidden failures."""
import pytest

from assistant.redaction import Redactor, redact

HELD_OUT = [
    ("phone spaces", "call me at 412 555 0199 anytime", "412 555 0199"),
    ("phone +1", "my cell is +1 412-555-0142", "412-555-0142"),
    ("ssn dashes", "SSN 912-34-5678", "912-34-5678"),
    ("ssn spaces", "SSN 912 34 5678", "912 34 5678"),
    ("apostrophe surname", "This is Sean O'Brien writing", "O'Brien"),
    ("last, first", "Kessler, Jordan called today", "Kessler"),
    ("three-part name", "Mary Ann Whitfield is my mother", "Whitfield"),
    ("dob words", "born on the 3rd of May 1990", "May 1990"),
    ("member id spaced", "member id HPX 884 712 035", "884 712 035"),
    ("dob short", "DOB 3/4/87", "3/4/87"),
    ("my name is, lowercase", "my name is jordan kessler", "kessler"),
    ("email", "write to j.kessler@gmail.com", "j.kessler@gmail.com"),
    ("address", "send it to 4410 Forbes Ave, Pittsburgh, PA 15213", "4410 Forbes Ave"),
]

KNOWN_GAPS = [
    ("lowercase name mid-sentence", "hi it's jordan kessler again", "kessler"),
    ("street without suffix", "I live at 55 Elm near the park", "55 Elm"),
    ("spelled-out email", "jordan dot kessler at gmail dot com", "kessler at gmail"),
]


@pytest.mark.parametrize("name,text,secret", HELD_OUT, ids=[c[0] for c in HELD_OUT])
def test_held_out_formats(name, text, secret):
    assert secret not in redact(text).text


@pytest.mark.xfail(reason="known limitation, documented in README", strict=True)
@pytest.mark.parametrize("name,text,secret", KNOWN_GAPS, ids=[c[0] for c in KNOWN_GAPS])
def test_known_gaps(name, text, secret):
    assert secret not in redact(text).text


def test_first_names_kept_and_deadlines_kept():
    out = redact("Hi Monica, Quinn Hargrove here. Please reply by November 13.").text
    assert "Quinn" in out and "Hargrove" not in out and "November 13" in out


def test_restore_round_trip():
    r = Redactor()
    safe = r.redact("Call Jordan Kessler at (412) 555-0101.")
    assert "555-0101" not in safe
    model_output = f"Draft: I will call {safe.split('at ')[1]}"
    assert "(412) 555-0101" in r.restore(model_output)


def test_same_value_same_placeholder():
    r = Redactor()
    a = r.redact("phone (412) 555-0101")
    b = r.redact("again (412) 555-0101")
    assert a.split()[-1] == b.split()[-1]
