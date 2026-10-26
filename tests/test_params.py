"""Every number must carry provenance; invalid configurations must be rejected."""
import pytest

from ueic.params import REGISTRY, make_config


def test_every_parameter_has_provenance():
    for p in REGISTRY.values():
        assert p.evidence in "ABCDEFG" and len(p.evidence) == 1, p.name
        assert p.source.strip(), p.name
        assert p.unit.strip(), p.name


def test_uncertain_parameters_have_sensitivity_ranges():
    for p in REGISTRY.values():
        if p.evidence in "EF" and p.group not in ("loop",) and p.name not in ("flow_design_lpm",):
            assert p.low is not None and p.high is not None, p.name
            assert p.low <= p.value <= p.high, p.name


def test_unknown_override_is_rejected():
    with pytest.raises(KeyError):
        make_config({"not_a_param": 1.0})


@pytest.mark.parametrize("over", [{"eta_pump": 1.5}, {"c_th": -1.0}, {"t_target": 90.0}, {"s_min": 1.2},
                                  {"dt": 120.0}])
def test_invalid_values_are_rejected(over):
    with pytest.raises(ValueError):
        make_config(over)
