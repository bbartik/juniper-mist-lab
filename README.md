# juniper-mist-lab — retail RF/WLAN example config

Example Mist org config for a fictional retail chain, used to exercise
RF Templates, Device Profiles, WLAN Templates, and Sites via the Mist API.
Everything is prefixed `BB-` to stay identifiable and safely deletable in a
shared org.

## Scenario

Four site formats, two example sites each:

| Format | Sites | Distinguishing choice |
|---|---|---|
| Distribution Center | Dallas, Reno | 2.4GHz kept alive for legacy scanners, high power/wide channels for open warehouse floors |
| Corporate Office | Austin HQ, Chicago | 2.4GHz off, narrow channels for AP-dense floors, 802.1X staff SSID |
| Retail - standalone | Denver #0142, Columbus #0210 | Baseline RF, no neighboring-tenant contention |
| Retail - mall-colocated | Scottsdale #0087, King of Prussia #0311 | Same WLANs as standalone, but a much lower power ceiling + narrower channels to avoid interfering with neighboring tenants' APs |
| Pop-up | NYC Holiday, Austin SXSW | Everything PSK (no RADIUS/portal backend worth standing up for a multi-week site), mesh-enabled device profile for uncabled spaces |

Full reasoning for each choice is in the `comment` fields inside the YAML files.

## Layout

```
config/
  site_groups.yaml      org/sitegroups
  rf_profiles.yaml      org/rftemplates    — bound to sites via rftemplate_id
  device_profiles.yaml  org/deviceprofiles — NOT bound anywhere by push.py; see note below
  wlan_templates.yaml   org/templates + org/wlans — bound to site groups via applies.sitegroup_ids
  sites.yaml            org/sites
scripts/
  mist_client.py        thin API wrapper + idempotent upsert-by-name
  discover.py           read-only: confirms the token works, lists org/sites
  push.py               idempotent create-or-update from the YAML above
  teardown.py           deletes exactly what push.py created (dry-run by default)
state/
  created_objects.json  written by push.py, read by teardown.py — not the YAML, THIS is the source of truth for what to delete
```

**Device profiles aren't bound to a site by push.py.** 
- Mist assigns them per-AP (`ap.deviceprofile_id`), not per-site - there's no site-level "default
device profile" field in the API. 
- There's no physical/virtual hardware in this lab to claim, so the four `BB-DP-*` profiles are created and ready, but
applying one means claiming a real AP into a site and setting its `deviceprofile_id`.

## Wired

Three Network Templates (`org/networktemplates`, pull-based via `site.networktemplate_id`, same mechanism as RF templates):

- **`BB-NT-Retail`** — one Virtual Chassis stack (1-3 switches), flat port map, no core/IDF split.
- **`BB-NT-DistributionCenter`** / **`BB-NT-CorporateOffice`** — Core of 2 (EVPN Multihoming) + 1 IDF. One template handles both switch roles via `switch_matching` rules keyed on switch hostname (`match_name` regex), not separate templates per role.

**What this does and doesn't cover:** the VLANs and per-port-role behavior (`switch_matching`) are fully modeled and bound to sites now. The actual EVPN Multihoming underlay — BGP peering, loopbacks, which physical ports become the ESI-LAG — is wizard-driven in Mist and tied to real cabling choices made when switches are claimed, so it isn't something this repo can pre-stage without hardware (same boundary as device profiles and AP claiming). What *is* pre-staged: the moment a switch is claimed and named to match the convention below, its ports already have correct role-based config.

Naming convention the `switch_matching` rules depend on:
```
<site-name>-CORE-1, <site-name>-CORE-2   (the EVPN Multihoming core pair)
<site-name>-IDF-1                        (the access closet)
```
e.g. `BB-DC-Dallas-01-CORE-1`, `BB-DC-Dallas-01-IDF-1`.

Wired VLANs intentionally use a separate numbering range (100s retail, 200s DC, 300s office) from the wireless VLANs (10-45) rather than reusing them — see `config/network_templates.yaml`. AP-facing trunk ports still need to carry the wireless VLANs, though, so each network template redeclares the relevant wireless VLAN IDs under its own `networks` block purely so port_usages can reference them by name.

## Adding a new store or DC

You never clone a WLAN/RF template per site — that's the whole point of site groups. You add one entry to `sites.yaml`:

```yaml
- name: BB-Retail-Phoenix-0455
  address: "Phoenix, AZ, USA"
  timezone: America/Phoenix
  site_group: BB-SG-RetailStandalone
  notes: "New store"
  vars:
    store_number: "0455"
```

...and its `pos_psk` in `config/secrets.yaml` (gitignored — see "Secrets" below):

```yaml
site_vars:
  BB-Retail-Phoenix-0455:
    pos_psk: "<a real passphrase>"
```

`rf_profile`, `device_profile`, and `country_code` are inherited from `site_defaults[site_group]` in `sites.yaml` unless you override them on the site itself — see the commented-out example at the bottom of that file. Run `python scripts/push.py`; the new site gets created, everything else comes back as a no-op `updated`. It's in `BB-SG-RetailStandalone`, so it picks up `BB-WLAN-Retail`'s SSIDs immediately — no separate WLAN step.

## Secrets

Every real WLAN passphrase lives in `config/secrets.yaml`, gitignored and never committed. Tracked YAML only ever holds a reference to it: `psk: "!secret"` in `wlan_templates.yaml` (resolved by `push.py`, keyed by SSID) or an omitted `pos_psk` in a site's `vars` (resolved from `secrets.yaml`'s `site_vars`, keyed by site name, and merged in before `push.py` writes `site.vars`). `config/secrets.example.yaml` is the tracked
template — copy it to `config/secrets.yaml` and fill in real values on a fresh clone. `push.py` refuses to run without that file present.

The RADIUS `secret: REPLACE_ME` in `wlan_templates.yaml`/`network_templates.yaml` is a genuine placeholder, not a real credential — it's fine to stay in git as-is until a real RADIUS server is wired up.

## Site variables (Mist-native, not something this repo invents)

Confirmed live against this org: `site.vars` is a real field (Mist just omits it from API responses when empty, which is why it doesn't show up until you set it). Any WLAN/network/gateway template field written as
`{{key}}` resolves from the target site's own `vars` when Mist pushes config to that site's devices — this is already how `CHAMPS`'s `{{SSID_Name}}` SSID in this org works.

`BB-Retail-POS` uses it for real: its `psk` in `wlan_templates.yaml` is the literal string `"{{pos_psk}}"`, and each retail site in `sites.yaml` defines its own `vars.pos_psk`. One WLAN definition, applied via one site group to every retail store, and every store still broadcasts a different actual passphrase. Same pattern works for anything else that should vary per site while sharing one template — a portal welcome message, a VLAN offset, a hostname prefix.

The API only round-trips the literal `{{pos_psk}}` string back to you — the substitution happens when Mist renders config for that site's actual devices, so there's nothing to see over the API without a claimed AP.

## Usage

```bash
pip install -r requirements.txt
python scripts/discover.py        # sanity check: token works, lists current sites
python scripts/push.py            # idempotent — safe to re-run after editing YAML
python scripts/teardown.py        # dry run, lists what would be deleted
python scripts/teardown.py --yes  # actually deletes it
```

`push.py` matches every object by `name` and updates in place rather than duplicating, so editing a YAML file and re-running is the normal workflow — no separate "diff" step needed.

## Should this live in YAML instead of just clicking around in Mist?

For a one-off demo, no - Mist's own template/site-group model already gives you reuse (bind one WLAN template to a site group, all 6 stores update together) and there's a real UI to look at while you build it. Don't reach for YAML+scripts just because it feels more rigorous.

It earns its keep here for a few specific reasons that apply to *this* repo:

- **This is a shared org.** Other engineers have live work in it. A script that only touches objects it created and tracks them in
  `state/created_objects.json` is a much safer way to add and later fully
  remove a 24-object footprint than doing it by hand and hoping you remember
  every name later.
- **Teardown/rebuild is the actual use case.** This is a *lab* — you'll
  probably blow it away and recreate it more than once as you test things.
  `teardown.py --yes` + `push.py` gives you a clean reset in seconds instead
  of manually hunting down 5 RF templates, 4 device profiles, 4 WLAN
  templates, ~10 WLANs, 5 site groups, and 10 sites in the UI.
- **The retail-specific reasoning is worth keeping somewhere durable.**
  *Why* the mall profile caps power at 11dBm, *why* the DC WLAN is WPA2-only
  — that context lives in the `comment` fields next to the values, not
  scattered across change-log entries or someone's memory. Mist's own audit
  log records *that* something changed, not *why*.
- **Git diff review before it touches a shared org.** You can see exactly
  what a change will do before `push.py` runs, which matters more here than
  it would in a personal sandbox.

What it's *not* a substitute for: Mist's own template/site-group inheritance, which already handles "update once, apply everywhere" for anything you're willing to manage by hand in the UI. This repo only adds value on top of that for the specific things above — repeatable teardown, shared-org safety, and keeping the "why" attached to the config.
