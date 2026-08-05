# Copyright 2026 Jared Medeiros
# SPDX-License-Identifier: Apache-2.0
# Part of DLPaC (https://github.com/s0undsystem/DLP-as-Code). See NOTICE.

"""Compiler unit tests. Runnable with pytest OR directly: `python tests/test_compiler.py`.

No tenant access; pure transformation tests against the sample catalog.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
# Repo root on the path so `compiler` imports as a package without needing an install.
# `pip install -e .` makes even this unnecessary.
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from compiler import compile as c  # noqa: E402
from compiler.resolver import load_catalog, ResolutionError  # noqa: E402

CATALOG = load_catalog(os.path.join(ROOT, "catalog", "catalog.json"))
ARCHETYPES = os.path.join(ROOT, "archetypes")

PILOT_GROUP = "dlp-pilot-group"
PILOT_GUID = "00000000-0000-0000-0000-000000000001"


def _friendly_policy():
    return {
        "name": "unit-test-pci-teams",
        "archetype": "group-scoped-simulation",
        "description": "unit test",
        "locations": {"teams": True},
        "rules": [{
            "name": "unit-test-pci-teams-rule",
            "operator": "And",
            "detect": {"groups": [{
                "name": "PCI",
                "operator": "Or",
                "sensitiveTypes": [
                    {"name": "Credit Card Number", "confidence": "Low"},
                    {"name": "U.S. Social Security Number (SSN)", "confidence": "Low"},
                ],
            }]},
        }],
    }


def test_archetype_supplies_mode_and_scope():
    entry = c.compile_policy(_friendly_policy(), CATALOG, ARCHETYPES)
    assert entry["mode"] == "TestWithoutNotifications"
    assert entry["locations"]["TeamsLocation"] == [PILOT_GUID]


def test_advanced_rule_shape_and_guids():
    entry = c.compile_policy(_friendly_policy(), CATALOG, ARCHETYPES)
    adv = json.loads(entry["rules"][0]["advancedRule"])
    assert adv["Version"] == "1.0"
    ccsi = [s for s in adv["Condition"]["SubConditions"]
            if s["ConditionName"] == "ContentContainsSensitiveInformation"][0]
    group = ccsi["Value"][0]["groups"][0]
    names = {t["name"]: t["id"] for t in group["sensitivetypes"]}
    assert names["Credit Card Number"] == "50842eb7-edc8-4019-85dd-5a5c1f2bb085"
    assert names["U.S. Social Security Number (SSN)"] == "a44669fe-0d48-453d-a9b1-2cc83f2cba77"


def test_raw_advanced_rule_passthrough():
    raw = '{"Version":"1.0","Condition":{"Operator":"And","SubConditions":[]}}'
    pol = {
        "name": "unit-test-raw",
        "mode": "TestWithNotifications",
        "scope": {"group": PILOT_GROUP},
        "locations": {"exchange": True},
        "rules": [{"name": "unit-test-raw-rule", "rawAdvancedRule": raw}],
    }
    entry = c.compile_policy(pol, CATALOG, ARCHETYPES)
    assert entry["rules"][0]["advancedRule"] == raw
    assert entry["locations"]["ExchangeLocation"] == ["All"]
    assert entry["locations"]["ExchangeSenderMemberOf"] == [PILOT_GUID]


def test_unknown_sit_fails_closed():
    bad = _friendly_policy()
    bad["rules"][0]["detect"]["groups"][0]["sensitiveTypes"] = [{"name": "Totally Made Up SIT"}]
    try:
        c.compile_policy(bad, CATALOG, ARCHETYPES)
        raise AssertionError("expected ResolutionError for unknown SIT")
    except ResolutionError:
        pass


def test_schema_rejects_missing_rules():
    bad = _friendly_policy()
    del bad["rules"]
    try:
        c.compile_policy(bad, CATALOG, ARCHETYPES)
        raise AssertionError("expected schema ValueError for missing rules")
    except ValueError:
        pass


def test_access_scope_condition():
    pol = {
        "name": "t-scope", "mode": "TestWithNotifications",
        "scope": {"group": PILOT_GROUP},
        "locations": {"exchange": True},
        "rules": [{"name": "r", "detect": {
            "accessScope": "NotInOrganization",
            "groups": [{"name": "PCI", "sensitiveTypes": [{"name": "Credit Card Number"}]}],
        }}],
    }
    adv = json.loads(c.compile_policy(pol, CATALOG, ARCHETYPES)["rules"][0]["advancedRule"])
    scope = [s for s in adv["Condition"]["SubConditions"] if s["ConditionName"] == "AccessScope"]
    assert scope and scope[0]["Value"] == "NotInOrganization"


def test_label_detection():
    pol = {
        "name": "t-label", "mode": "TestWithNotifications",
        "scope": {"group": PILOT_GROUP},
        "locations": {"sharePoint": True},
        "rules": [{"name": "r", "detect": {"groups": [{"name": "labeled", "labels": ["Confidential"]}]}}],
    }
    adv = json.loads(c.compile_policy(pol, CATALOG, ARCHETYPES)["rules"][0]["advancedRule"])
    grp = adv["Condition"]["SubConditions"][0]["Value"][0]["groups"][0]
    assert grp["labels"][0]["name"] == CATALOG.labels["Confidential"]
    assert grp["labels"][0]["type"] == "Sensitivity"


def test_full_fidelity_actions():
    pol = {
        "name": "t-actions", "mode": "TestWithNotifications",
        "scope": {"group": PILOT_GROUP},
        "locations": {"exchange": True},
        "rules": [{
            "name": "r",
            "detect": {"groups": [{"name": "PCI", "sensitiveTypes": [{"name": "Credit Card Number"}]}]},
            "actions": {
                "blockAccess": True, "blockAccessScope": "All",
                "notifyUser": ["Owner", "LastModifier"],
                "notifyPolicyTipText": "Sensitive.",
                "notifyEmail": {"text": "body", "subject": "subj"},
                "generateAlert": ["admin@example.com"],
                "alertProperties": {"aggregationType": "None"},
                "generateIncidentReport": ["admin@example.com"],
                "incidentReportContent": ["All"],
            },
        }],
    }
    params = c.compile_policy(pol, CATALOG, ARCHETYPES)["rules"][0]["params"]
    assert params["BlockAccess"] is True
    assert params["BlockAccessScope"] == "All"
    assert params["NotifyUser"] == ["Owner", "LastModifier"]
    assert params["NotifyPolicyTipCustomText"] == "Sensitive."
    assert params["NotifyEmailCustomText"] == "body" and params["NotifyEmailCustomSubject"] == "subj"
    assert params["GenerateAlert"] == ["admin@example.com"]
    assert params["AlertProperties"] == {"aggregationType": "None"}
    assert params["GenerateIncidentReport"] == ["admin@example.com"]
    assert params["IncidentReportContent"] == ["All"]


def _copilot_policy():
    return {
        "name": "unit-test-copilot",
        "mode": "TestWithoutNotifications",
        "scope": {"users": ["user@example.com", "another.user@example.com"]},
        "locations": {"copilot": True},
        "rules": [{
            "name": "unit-test-copilot-rule",
            "hasActivity": "UploadText",
            "detect": {"groups": [{
                "name": "Credentials",
                "sensitiveTypes": [{"name": "Example Credential SIT", "confidence": "Medium"}],
            }]},
        }],
    }


def test_copilot_locations_blob():
    entry = c.compile_policy(_copilot_policy(), CATALOG, ARCHETYPES)
    locs = json.loads(entry["copilotLocations"])
    assert len(locs) == 1
    assert locs[0]["Workload"] == "Applications"
    assert locs[0]["Location"] == "Copilot.M365"
    assert locs[0]["Inclusions"] == [
        {"Type": "IndividualResource", "Identity": "user@example.com"},
        {"Type": "IndividualResource", "Identity": "another.user@example.com"},
    ]


def test_copilot_enforcement_planes():
    entry = c.compile_policy(_copilot_policy(), CATALOG, ARCHETYPES)
    assert entry["enforcementPlanes"] == ["CopilotExperiences"]


def test_copilot_rule_carries_restrict_access():
    """Purview rejects a Copilot rule with no restrict action. The value-only shape matters:
    a "setting" key alongside a HasActivity condition is rejected by the service."""
    entry = c.compile_policy(_copilot_policy(), CATALOG, ARCHETYPES)
    for rule in entry["rules"]:
        assert rule["params"]["RestrictAccess"] == [{"value": "Block"}]
        assert "setting" not in rule["params"]["RestrictAccess"][0]


def test_non_copilot_policy_has_no_copilot_keys():
    entry = c.compile_policy(_friendly_policy(), CATALOG, ARCHETYPES)
    assert "copilotLocations" not in entry
    assert "enforcementPlanes" not in entry
    assert "RestrictAccess" not in entry["rules"][0]["params"]


def test_example_copilot_policy_compiles():
    """The shipped example must compile and carry the full Copilot envelope."""
    path = os.path.join(ROOT, "policies", "example-copilot-secrets.yaml")
    entry = c.compile_policy(c.load_yaml(path), CATALOG, ARCHETYPES)
    assert json.loads(entry["copilotLocations"])[0]["Location"] == "Copilot.M365"
    assert entry["enforcementPlanes"] == ["CopilotExperiences"]
    assert entry["rules"][0]["params"]["RestrictAccess"] == [{"value": "Block"}]


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"FAIL  {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
