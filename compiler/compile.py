#!/usr/bin/env python3
"""Compile YAML DLP definitions into a deploy manifest.

policies/*.yaml (+ archetypes/*.yaml) -> validate -> resolve names to GUIDs ->
build/manifest.json, describing the New/Set-DlpCompliancePolicy envelope parameters and
the AdvancedRule JSON for each rule. Pure transformation; no tenant access required.

The AdvancedRule shape matches the write form validated against the live tenant on
2026-07-27 (see docs/phase2-build-plan.md, Task 0): PascalCase envelope
(Version/Condition/SubConditions/ConditionName) with a lowercase detection body
(groups/name/sensitivetypes/{name,id,confidencelevel,...}).
"""
import argparse
import glob
import json
import os
import sys
from collections import OrderedDict

import yaml

from resolver import load_catalog, ResolutionError
from validate import validate_policy

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))


def _deep_merge(base, override):
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_yaml(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def apply_archetype(raw, archetype_dir):
    """Merge an archetype (if referenced) under the policy; policy keys win."""
    arch = raw.get("archetype")
    body = {k: v for k, v in raw.items() if k != "archetype"}
    if not arch:
        return body
    apath = os.path.join(archetype_dir, arch + ".yaml")
    if not os.path.exists(apath):
        raise ValueError(f"archetype '{arch}' not found at {apath}")
    base = load_yaml(apath) or {}
    base = {k: v for k, v in base.items() if not str(k).startswith("_")}
    return _deep_merge(base, body)


def build_locations(policy, catalog):
    """Translate the DSL `locations` + `scope.group` into cmdlet scoping parameters."""
    locs = policy.get("locations", {})
    scope = policy.get("scope") or {}
    group_name = scope.get("group")
    group_guid = catalog.group(group_name) if group_name else None
    params = OrderedDict()
    if locs.get("exchange"):
        params["ExchangeLocation"] = ["All"]
        if group_guid:
            params["ExchangeSenderMemberOf"] = [group_guid]
    if locs.get("teams"):
        params["TeamsLocation"] = [group_guid] if group_guid else ["All"]
    sp = locs.get("sharePoint")
    if sp:
        params["SharePointLocation"] = [catalog.site(sp)] if isinstance(sp, str) else ["All"]
    if locs.get("oneDrive"):
        params["OneDriveLocation"] = ["All"]
        if group_guid:
            params["OneDriveSharedByMemberOf"] = [group_guid]
    if locs.get("endpoint"):
        params["EndpointDlpLocation"] = [group_guid] if group_guid else ["All"]
    return params


def build_advanced_rule(rule, catalog):
    """Build the AdvancedRule JSON string in the validated write form.

    If `rawAdvancedRule` is supplied (e.g. a policy codified from an existing tenant rule),
    use it verbatim — GUIDs are already embedded, so no resolution is needed.
    """
    if rule.get("rawAdvancedRule"):
        return rule["rawAdvancedRule"]
    detect = rule["detect"]
    groups_out = []
    for g in detect["groups"]:
        grp = OrderedDict([("Operator", g.get("operator", "Or")), ("name", g["name"])])
        if g.get("sensitiveTypes"):
            sits = []
            for st in g["sensitiveTypes"]:
                resolved = catalog.sit(st["name"])
                e = OrderedDict([("name", resolved["name"]), ("id", resolved["id"])])
                if "confidence" in st:
                    e["confidencelevel"] = st["confidence"]
                if "minCount" in st:
                    e["mincount"] = str(st["minCount"])
                if "maxCount" in st:
                    e["maxcount"] = str(st["maxCount"])
                sits.append(e)
            grp["sensitivetypes"] = sits
        if g.get("labels"):
            grp["labels"] = [catalog.label(name) for name in g["labels"]]
        groups_out.append(grp)

    ccsi = OrderedDict([
        ("ConditionName", "ContentContainsSensitiveInformation"),
        ("Value", [OrderedDict([("groups", groups_out)])]),
    ])
    subconditions = []
    if rule.get("hasActivity"):
        subconditions.append(OrderedDict([("ConditionName", "HasActivity"), ("Value", rule["hasActivity"])]))
    subconditions.append(ccsi)
    if detect.get("accessScope"):
        subconditions.append(OrderedDict([("ConditionName", "AccessScope"), ("Value", detect["accessScope"])]))

    advanced = OrderedDict([
        ("Version", "1.0"),
        ("Condition", OrderedDict([
            ("Operator", rule.get("operator", "And")),
            ("SubConditions", subconditions),
        ])),
    ])
    return json.dumps(advanced, separators=(",", ":"))


def build_rule_params(actions):
    """Map the DSL `actions` block to New/Set-DlpComplianceRule parameters (full fidelity).

    These are separate cmdlet parameters (not part of AdvancedRule); the deploy step splats them.
    generateAlert / generateIncidentReport are emitted only when given as recipient lists — a bare
    boolean (as produced when codifying existing rules) is documentation, not a deployable value.
    """
    actions = actions or {}
    p = OrderedDict()
    if "blockAccess" in actions:
        p["BlockAccess"] = bool(actions["blockAccess"])
    if actions.get("blockAccessScope"):
        p["BlockAccessScope"] = actions["blockAccessScope"]
    if actions.get("notifyUser"):
        p["NotifyUser"] = list(actions["notifyUser"])
    if actions.get("notifyPolicyTipText"):
        p["NotifyPolicyTipCustomText"] = actions["notifyPolicyTipText"]
    notify_email = actions.get("notifyEmail") or {}
    if notify_email.get("text"):
        p["NotifyEmailCustomText"] = notify_email["text"]
    if notify_email.get("subject"):
        p["NotifyEmailCustomSubject"] = notify_email["subject"]
    alert = actions.get("generateAlert")
    if isinstance(alert, list):
        p["GenerateAlert"] = list(alert)
    if actions.get("alertProperties"):
        p["AlertProperties"] = actions["alertProperties"]
    incident = actions.get("generateIncidentReport")
    if isinstance(incident, list):
        p["GenerateIncidentReport"] = list(incident)
    if actions.get("incidentReportContent"):
        p["IncidentReportContent"] = list(actions["incidentReportContent"])
    return p


def compile_rule(rule, catalog):
    entry = OrderedDict([
        ("name", rule["name"]),
        ("advancedRule", build_advanced_rule(rule, catalog)),
    ])
    if rule.get("rawAdvancedRule"):
        # Codified-from-live rule: detection is verbatim; actions are documentation only.
        entry["params"] = OrderedDict()
        if rule.get("actions"):
            entry["actionsObserved"] = rule["actions"]
    else:
        entry["params"] = build_rule_params(rule.get("actions") or {})
    return entry


def compile_policy(raw, catalog, archetype_dir):
    merged = apply_archetype(raw, archetype_dir)
    validate_policy(merged)
    entry = OrderedDict()
    entry["name"] = merged["name"]
    entry["mode"] = merged["mode"]
    if merged.get("description"):
        entry["comment"] = merged["description"]
    if merged.get("priority") is not None:
        entry["priority"] = merged["priority"]
    entry["locations"] = build_locations(merged, catalog)
    # Copilot scopes to individual users (no simple location param) — capture for the record.
    if merged.get("locations", {}).get("copilot"):
        entry["copilotUsers"] = list((merged.get("scope") or {}).get("users") or [])
    entry["rules"] = [compile_rule(r, catalog) for r in merged["rules"]]
    return entry


def compile_all(policies_dir, archetype_dir, catalog):
    files = sorted(
        glob.glob(os.path.join(policies_dir, "*.yaml"))
        + glob.glob(os.path.join(policies_dir, "*.yml"))
    )
    out = []
    for path in files:
        raw = load_yaml(path)
        if not raw:
            continue  # skip empty placeholder files
        out.append(compile_policy(raw, catalog, archetype_dir))
    return OrderedDict([("policies", out)])


def main(argv=None):
    ap = argparse.ArgumentParser(description="Compile YAML DLP definitions to a deploy manifest.")
    ap.add_argument("--policies", default=os.path.join(ROOT, "policies"))
    ap.add_argument("--archetypes", default=os.path.join(ROOT, "archetypes"))
    ap.add_argument("--catalog", default=os.path.join(ROOT, "catalog", "catalog.json"))
    ap.add_argument("--out", default=os.path.join(ROOT, "build", "manifest.json"))
    args = ap.parse_args(argv)

    catalog = load_catalog(args.catalog)
    try:
        manifest = compile_all(args.policies, args.archetypes, catalog)
    except (ValueError, ResolutionError) as e:
        print(f"COMPILE ERROR: {e}", file=sys.stderr)
        return 1

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print(f"Compiled {len(manifest['policies'])} policy(ies) -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
