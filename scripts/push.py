"""Idempotent push of config/*.yaml into the Mist org referenced by .env.

Order matters: site groups first (WLAN templates apply to them), then RF
profiles, device profiles, WLAN templates + their WLANs, and network
templates (all referenced by name from sites.yaml), then sites last (which
bind rftemplate_id, networktemplate_id, and sitegroup_ids).

Re-running is safe: objects are matched by `name` and updated in place rather
than duplicated. Every created/updated id is recorded in state/created_objects.json
so teardown.py can remove exactly these objects later.
"""
import copy
import json
import os
import sys

import yaml

from mist_client import MistClient

CONFIG_DIR = os.path.join(os.path.dirname(__file__), "..", "config")
STATE_PATH = os.path.join(os.path.dirname(__file__), "..", "state", "created_objects.json")
SECRETS_PATH = os.path.join(CONFIG_DIR, "secrets.yaml")

# Keys that exist in the YAML for documentation/cross-referencing but aren't
# real Mist API fields — stripped before any object is sent.
NON_API_KEYS = {"comment", "applies_sitegroups", "site_group", "rf_profile", "device_profile",
                 "network_template"}


def load(name):
    with open(os.path.join(CONFIG_DIR, f"{name}.yaml"), encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_secrets():
    if not os.path.exists(SECRETS_PATH):
        sys.exit(
            f"Missing {SECRETS_PATH}. Copy config/secrets.example.yaml to "
            f"config/secrets.yaml and fill in real values."
        )
    with open(SECRETS_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def clean(obj):
    obj = copy.deepcopy(obj)
    for k in NON_API_KEYS:
        obj.pop(k, None)
    return obj


def load_state():
    state = {"site_groups": {}, "rf_profiles": {}, "device_profiles": {},
              "wlan_templates": {}, "wlans": {}, "network_templates": {}, "sites": {}}
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH, encoding="utf-8") as f:
            state.update(json.load(f))
    return state


def save_state(state):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def main():
    client = MistClient()
    state = load_state()
    secrets = load_secrets()

    # 1. Site groups
    for sg in load("site_groups")["site_groups"]:
        sid, action = client.upsert_by_name(client.org_path("/sitegroups"), sg["name"], clean(sg))
        state["site_groups"][sg["name"]] = sid
        print(f"[site_group] {sg['name']}: {action} ({sid})")

    # 2. RF profiles
    for rf in load("rf_profiles")["rf_profiles"]:
        rid, action = client.upsert_by_name(client.org_path("/rftemplates"), rf["name"], clean(rf))
        state["rf_profiles"][rf["name"]] = rid
        print(f"[rf_profile] {rf['name']}: {action} ({rid})")

    # 3. Device profiles
    for dp in load("device_profiles")["device_profiles"]:
        did, action = client.upsert_by_name(client.org_path("/deviceprofiles"), dp["name"], clean(dp))
        state["device_profiles"][dp["name"]] = did
        print(f"[device_profile] {dp['name']}: {action} ({did})")

    # 4. WLAN templates + WLANs
    for wt in load("wlan_templates")["wlan_templates"]:
        sitegroup_ids = [state["site_groups"][n] for n in wt.get("applies_sitegroups", [])]
        wt_body = clean(wt)
        wt_body["applies"] = {"sitegroup_ids": sitegroup_ids, "site_ids": []}
        wt_id, action = client.upsert_by_name(client.org_path("/templates"), wt["name"], wt_body)
        state["wlan_templates"][wt["name"]] = wt_id
        print(f"[wlan_template] {wt['name']}: {action} ({wt_id})")

        existing_wlans = client.get(client.org_path("/wlans"))
        existing_by_key = {
            (w["template_id"], w["ssid"]): w["id"]
            for w in existing_wlans if w.get("template_id") == wt_id
        }

        for wlan in wt.get("wlans", []):
            body = clean(wlan)
            if body.get("auth", {}).get("psk") == "!secret":
                wlan_psks = secrets.get("wlan_psks", {})
                if wlan["ssid"] not in wlan_psks:
                    sys.exit(f"No wlan_psks entry for {wlan['ssid']} in {SECRETS_PATH}")
                body["auth"]["psk"] = wlan_psks[wlan["ssid"]]
            body["template_id"] = wt_id
            key = (wt_id, wlan["ssid"])
            if key in existing_by_key:
                wlan_id = existing_by_key[key]
                client.put(client.org_path(f"/wlans/{wlan_id}"), body)
                action = "updated"
            else:
                created = client.post(client.org_path("/wlans"), body)
                wlan_id = created["id"]
                action = "created"
            state["wlans"][f"{wt['name']}/{wlan['ssid']}"] = wlan_id
            print(f"  [wlan] {wlan['ssid']}: {action} ({wlan_id})")

    # 5. Network templates (pull-based, like RF profiles — bound via site.networktemplate_id)
    for nt in load("network_templates")["network_templates"]:
        nid, action = client.upsert_by_name(client.org_path("/networktemplates"), nt["name"], clean(nt))
        state["network_templates"][nt["name"]] = nid
        print(f"[network_template] {nt['name']}: {action} ({nid})")

    # 6. Sites — merge each site's site_group defaults underneath its own fields
    sites_data = load("sites")
    site_defaults = sites_data.get("site_defaults", {})
    for raw_site in sites_data["sites"]:
        site = {**site_defaults.get(raw_site.get("site_group"), {}), **raw_site}
        site_vars = {**site.pop("vars", {}), **secrets.get("site_vars", {}).get(site["name"], {})}
        body = clean(site)
        body["rftemplate_id"] = state["rf_profiles"][site["rf_profile"]] if site.get("rf_profile") else None
        body["networktemplate_id"] = (
            state["network_templates"][site["network_template"]] if site.get("network_template") else None
        )
        body["sitegroup_ids"] = [state["site_groups"][site["site_group"]]] if site.get("site_group") else []
        site.pop("site_group", None)
        sid, action = client.upsert_by_name(
            client.org_path("/sites"), site["name"], body, item_base_path="/api/v1/sites"
        )
        state["sites"][site["name"]] = sid
        print(f"[site] {site['name']}: {action} ({sid})")

        # Site Variables live under the site's /setting sub-resource, NOT the
        # site object itself — the site object silently accepts a "vars" key
        # too, but the WLAN template renderer and the UI's Site Variables
        # panel only read from /api/v1/sites/{id}/setting.
        if site_vars:
            client.put(f"/api/v1/sites/{sid}/setting", {"vars": site_vars})
            print(f"  [vars] {list(site_vars.keys())}")

    save_state(state)
    print(f"\nState written to {STATE_PATH}")
    print("Note: device profiles are created but not bound anywhere — Mist assigns")
    print("them per-AP (ap.deviceprofile_id), not per-site. Claim an AP into a site")
    print("and set its deviceprofile_id to apply one.")


if __name__ == "__main__":
    main()
