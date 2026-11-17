# Upgrading from 0.1.x to 0.2.0

In 0.2.0 the integration was renamed from **ERM Zapad power outages** (`erm_zapad_outages`) to
**Bulgaria power outages** (`bg_power_outages`), and the repository moved from
`wildsystems/ws-erm-zapad-outages` to `wildsystems/ws-bg-power-outages`. Home Assistant treats the
renamed integration as a new one: it does not take over the existing entries. Remove them and add
them again. With the same values, the new entities get the same entity IDs.

> **Do not press Update in HACS.** HACS would install 0.2.0 into a new `bg_power_outages/` folder
> and leave the old `erm_zapad_outages/` folder in place, so Home Assistant would keep loading the
> old integration too. Follow the steps below instead. If you have already updated, see
> [step 3](#3-install-020).

The upgrade takes about 10 minutes and one restart. The full list of changes is in the
[changelog](../CHANGELOG.md).

## What carries over and what does not

| | after the upgrade |
|---|---|
| entity IDs | the same, if each entry is added again with the same values and the old entities were deleted first |
| history of the entities | kept: the recorder stores history by entity ID, so the graphs continue |
| automations, scripts, dashboards | keep working if they use entity IDs. Check the [behaviour changes](#6-check-automations-for-the-behaviour-changes) |
| automations from the alert blueprint | keep working once the blueprint is replaced (step 5) |
| device names you changed, entity IDs you changed, areas, labels, hidden or disabled entities | **lost**: set them again |
| last event of `event.<name>_new_outage_published` | lost; the state is `unknown` until the next new outage |

## 1. Write down your entries

For every **ERM Zapad power outages** entry (Settings → Devices & services → ERM Zapad power
outages), write down:

- the mode and the values: the client number, or the place and municipality as entered. **⋮ →
  Reconfigure** shows them; close the dialog without saving;
- the device name if you changed it, and its area;
- entity IDs that you changed, entities you hid or disabled, and labels. Settings → Entities,
  filtered by the integration, lists them all.

## 2. Delete the old entries

Delete every ERM Zapad power outages entry: **⋮ → Delete**. Its device and entities are removed,
which frees their entity IDs for the new entries. Do this before installing 0.2.0. If an old
entity is still registered when the new entry is added, the new entity gets a suffix, such as
`sensor.zlatusha_next_outage_2`.

Automations and dashboards that use the entities show them as unavailable until step 4.

## 3. Install 0.2.0

### HACS

1. HACS → **ERM Zapad power outages** → **⋮ → Remove**. This deletes
   `custom_components/erm_zapad_outages/`.
2. Download the integration again: HACS → search **Bulgaria power outages** or **ERM Zapad power
   outages**. If the repository is no longer listed, add it again: HACS → ⋮ → **Custom
   repositories** → `https://github.com/wildsystems/ws-bg-power-outages`, type **Integration**.
3. Download version 0.2.0 and restart Home Assistant.

Do not use **Update** for this upgrade. HACS installs 0.2.0 into the new
`custom_components/bg_power_outages/` folder but leaves the old `erm_zapad_outages/` folder in
place, so Home Assistant would keep loading the old integration too. If you already updated this
way, delete `custom_components/erm_zapad_outages/` (Samba, SSH or a file editor add-on) and
restart.

The old repository URL keeps working: GitHub redirects it, and HACS follows the new name.

### Manual

Delete `<config>/custom_components/erm_zapad_outages/`, copy `custom_components/bg_power_outages/`
to `<config>/custom_components/` and restart Home Assistant.

### After the restart

Settings → Devices & services must not show ERM Zapad power outages any more. An entry that was
not deleted in step 2 is shown there as not loaded; delete it now. Home Assistant deletes it even
though the integration is gone.

## 4. Add the entries again

Settings → Devices & services → Add integration → **Bulgaria power outages** → **ЕРМ Запад**,
then **By client number** or **By place**, with the values from step 1. Use the same spelling: the
device name, and with it the entity IDs, is made from these values.

Then:

1. Settings → Entities, filtered by Bulgaria power outages: check that the entity IDs match the
   old ones. An ID with a suffix (`_2`) means an old entity is still registered. Delete the old
   entity and rename the new one.
2. Set again the device names, areas, entity IDs, hidden or disabled entities and labels that you
   wrote down.

## 5. Replace the alert blueprint

Skip this step if you do not use the blueprint.

The blueprint moved to `blueprints/automation/bg_power_outages/outage_alert.yaml`. Its old
location no longer exists, so a re-import from the old source URL fails. Import it from the new
location:

[![Open your Home Assistant instance and show the blueprint import dialog.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fwildsystems%2Fws-bg-power-outages%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fbg_power_outages%2Foutage_alert.yaml)

Home Assistant saves an imported blueprint as `wildsystems/outage_alert.yaml`, the same path as
the old one. It reports that the blueprint already exists; overwrite it. Automations made from it
then use the new version with their current inputs, and the entity IDs are the same as before, so
nothing else has to be changed.

If the blueprint is at another path (for example, you copied the file yourself), copy the new
`outage_alert.yaml` over the old file and reload automations (Developer tools → YAML → Automations).

Check each automation made from the blueprint: open it and confirm that **New outage event** and
**Outage tomorrow sensor** still show the entities. Both must belong to the same entry.

## 6. Check automations for the behaviour changes

Most automations need no change. Check yours if they rely on the following.

- **ЕРМ Запад by place with a municipality** now also gets unplanned outages. `outage_now` is new
  for these entries; the calendar, `next_outage`, `next_outage_start`, `next_outage_end` and
  `outage_tomorrow` can now show unplanned outages as well. The event entity still fires only for
  planned outages. To react to planned outages only, check `kind` or the calendar summary, e.g.
  `trigger.calendar_event.summary.startswith('Планирано')`.
- **Requests:** those entries also check every 30 minutes for outages registered right now. With
  many of them, mind the ЕРМ Запад request limit (README, "Polling and request limits").
- **Calendar events by place:** the description now starts with the full place, names the operator
  and links its page instead of the client number check. Long places are cut to 60 characters in
  the summary and location. Templates that parse the description or the location may need a change.
- **Persistent notifications from the blueprint:** the notification ID now includes the
  automation (`bg_power_outage_<trigger>_<automation>`). Notifications created by 0.1.0 are not
  replaced by new ones; dismiss them once.
- **Blueprint trigger:** a state trigger on the event entity no longer has to exclude
  `unavailable` and `unknown`; the blueprint checks the event time instead. Your own automations
  should do the same, see [the example](automations.md#new-outage-published).
- **Repair issues** are titled `ЕРМ Запад answer not understood (…)` instead of `ERM Zapad answer
  not understood (…)`.

## Going back to 0.1.0

Delete the Bulgaria power outages entries, then in HACS remove the integration and download
version 0.1.0 of the repository again (or copy `custom_components/erm_zapad_outages/` from the
`v0.1.0` tag), restart, and add the entries again. The 0.1.0 blueprint is in the `v0.1.0` tag at
`blueprints/automation/erm_zapad_outages/outage_alert.yaml`.
