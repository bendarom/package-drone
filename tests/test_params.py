import pytest

from mav.params import (FAIL, MISSING, PASS, TBD, Expected, ParamFileError, check_params, compare,
                        load_expected, parse_expected)


def e(value, op="eq", tolerance=0.0, name="X"):
    return Expected(name, value, tolerance, op, "because")


@pytest.mark.parametrize("exp,actual,status", [
    (e(100), 100.0, PASS),
    (e(100), 101.0, FAIL),
    (e(0.1, tolerance=0.001), 0.10000000149, PASS),   # float32 round trip
    (e(0.1), 0.10000000149, PASS),                     # FLOAT_EPS covers float32 even at tolerance 0
    (e(3, tolerance=0.5), 3.4, PASS),
    (e(3, tolerance=0.5), 3.6, FAIL),
    (e(-1), -1.0, PASS),
    (e(1, op="ge"), 3.0, PASS),
    (e(1, op="ge"), 0.0, FAIL),
    (e(10, op="le"), 10.0, PASS),
    (e(10, op="le"), 11.0, FAIL),
    (e(0b101, op="bits_set"), 0b1111, PASS),
    (e(0b101, op="bits_set"), 0b0110, FAIL),
    (e(100), None, MISSING),
    (e(None), 5.0, TBD),
    (e(None), None, TBD),
])
def test_compare(exp, actual, status):
    assert compare(exp, actual) == status


def test_check_params_report(fake_log):
    entries = [e(1, name="A"), e(2, name="B"), e(None, name="C"), e(4, name="D")]
    values = {"A": 1.0, "B": 3.0, "C": 7.0}
    report = check_params(values.get, entries, fake_log, "test.yaml")
    assert [r.status for r in report.results] == [PASS, FAIL, TBD, MISSING]
    assert not report.ok
    assert report.results[2].actual == 7.0   # TBD entries still show the FC's value
    assert "FAILED" in report.summary()
    assert fake_log.kinds().count("param_check") == 4


def test_all_pass(fake_log):
    report = check_params(lambda n: 1.0, [e(1, name="A")], fake_log)
    assert report.ok and "PASSED" in report.summary()


def test_empty_list_is_not_ok():
    assert not check_params(lambda n: 1.0, []).ok


def test_parse_rejects_bad_entries():
    bad = {"params": [
        {"name": "lower", "value": 1, "reason": "r"},
        {"name": "A", "value": "x", "reason": "r"},
        {"name": "B", "value": 1, "op": "approx", "reason": "r"},
        {"name": "C", "value": 1},
        {"name": "D", "value": 1, "reason": "r", "tolerence": 1},
        {"name": "E", "value": 1, "reason": "r"},
        {"name": "E", "value": 2, "reason": "r"},
    ]}
    with pytest.raises(ParamFileError) as err:
        parse_expected(bad, "t.yaml")
    msg = str(err.value)
    for fragment in ("name must be an upper-case", "A: value must be a number", "B: op must be one of",
                     "C: reason is required", "D: unknown key(s) tolerence", "E: listed twice"):
        assert fragment in msg


def test_parse_needs_params_list():
    with pytest.raises(ParamFileError):
        parse_expected({"parameters": []})


@pytest.mark.parametrize("run_mode,file", [("sitl", "expected_sitl.yaml"), ("real", "expected_real.yaml"),
                                           ("shadow", "expected_real.yaml")])
def test_repo_expected_files_parse(run_mode, file):
    path, entries = load_expected(run_mode)
    assert path.name == file
    assert entries
    names = {x.name for x in entries}
    assert {"EK3_SRC1_POSZ", "EK3_RNG_USE_HGT", "RNGFND1_ORIENT", "MAV_SYSID"} <= names


def test_sitl_file_has_no_tbd():
    _, entries = load_expected("sitl")
    assert all(x.value is not None for x in entries)
