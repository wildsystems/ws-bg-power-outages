# Changelog

## 0.2.0

The integration now covers three Bulgarian distribution operators and continues **ERM Zapad power
outages** (`erm_zapad_outages`) as **Bulgaria power outages** (`bg_power_outages`), in the new
repository `wildsystems/ws-bg-power-outages`. The old repository `wildsystems/ws-erm-zapad-outages`
is no longer maintained; its last version, 0.1.1, shows a repair that points here.

> **Breaking – a new integration, not an update.** Home Assistant sees Bulgaria power outages as a
> new integration: existing entries are not taken over, they have to be added again, and the alert
> blueprint has to be imported again. Delete the old entries, uninstall ERM Zapad power outages,
> add this repository (Marketplace **Add from link**, or HACS **Custom repositories** on Home
> Assistant 2026.10 and older) and install Bulgaria power outages. Follow
> [docs/upgrade-0.2.md](docs/upgrade-0.2.md).

### Added

- Електроразпределение Юг (EVN, south-eastern Bulgaria): planned and unplanned outages by province
  and place, with an optional street or quarter.
- Електроразпределение Север (Energo-Pro, north-eastern Bulgaria): planned outages and "possible
  disturbance" announcements by province and place, with an optional street or quarter.
- ЕРМ Запад by place with a municipality: unplanned outages registered right now, and the
  `outage_now` binary sensor.
- Outage kind `possible` (Електроразпределение Север), shown in the calendar and the sensors but not
  counted by `outage_now`.
- A published period with daily hours ("16.11–20.11, 09:00–17:00") becomes one outage per day, for
  at most 31 days.
- [docs/automations.md](docs/automations.md): example automations for a new outage, an outage that
  starts or ends, a restore time that is announced, and a calendar reminder.
- README sections on calendar events, the next outage sensors, the new outage event, availability,
  and times and time zones.

### Changed

- Config flow: the operator is chosen first. ЕРМ Запад then asks for client number or place as
  before.
- Device manufacturer, entity attribution and repair issue title name the entry's operator instead
  of always ЕРМ Запад. The device link points to the operator's outage page (the client number check
  for ЕРМ Запад client numbers, as before).
- `outage_now` of place entries has the attribute `place` instead of `point`.
- Calendar events by place: the summary and the location cut long area descriptions to 60
  characters; the description starts with the full place or area description and names the
  operator and its page instead of the ЕРМ Запад client number check; a missing restore time is
  noted. The summary is `Възможни смущения в захранването – …` for `possible` outages.
- Alert blueprint, now `blueprints/automation/bg_power_outages/outage_alert.yaml`:
  - selects entities of `bg_power_outages`;
  - the title names the operator and the device (place or address);
  - outages are marked `непланирано` or `възможни смущения` by kind, and long area descriptions
    are shortened;
  - the persistent notification ID includes the automation, so several automations from the
    blueprint no longer replace each other's notification;
  - the trigger no longer excludes `unknown` and `unavailable`: an event that arrives as the entity
    becomes available again is not missed. Restored old events are still ignored by their time.
- Requests: each operator has its own shared client, rate limit back-off and download cache.

### Fixed

- The shared HTTP session was closed when the entry that created it failed to set up or was
  unloaded, so the other entries' refreshes failed until Home Assistant restarted.

### Upgrade impact for ЕРМ Запад places with a municipality

These entries now also check the outages registered right now every 30 minutes: one request for
the list of municipalities with an outage and, when the entry's municipality is in it, its outage
map. With many such entries, keep the ЕРМ Запад request limit in mind (see README, "Polling and
request limits"). Without a municipality nothing changes.

## 0.1.0

First release: ЕРМ Запад planned outages by place (daily PDF schedules) and planned and unplanned
outages by client number, with calendar, binary sensors, next outage sensors, a new outage event
and an alert blueprint.
