# Example automations

These examples are for an entry whose entities are named `…zlatusha…`. Replace those entity IDs
with your own, and `notify.mobile_app_phone` with your notification action. Why the examples are
built this way is explained in the [README](../README.md#entities-per-entry).

## New outage published

The [alert blueprint](../blueprints/automation/bg_power_outages/outage_alert.yaml) does the same
and also sends a reminder in the evening. This automation reacts only to an event that has just
fired. After a restart, a reload or an unavailable period, the event entity shows its last event
again, and that event's time is old.

```yaml
alias: Power outage published
triggers:
  - trigger: state
    entity_id: event.zlatusha_new_outage_published
conditions:
  - condition: template
    value_template: >-
      {{ trigger.to_state.state not in ['unknown', 'unavailable']
         and trigger.to_state.attributes.event_type == 'published'
         and now() - as_datetime(trigger.to_state.state) < timedelta(minutes=5) }}
actions:
  - action: notify.mobile_app_phone
    data:
      title: Ново прекъсване на тока
      message: |-
        {% for o in trigger.to_state.attributes.outages -%}
        {{ as_datetime(o.start).strftime('%d.%m %H:%M') }}–{{
           as_datetime(o.end).strftime('%H:%M') if o.end else '?' }} {{ o.place | truncate(120) }}
        {% endfor %}
```

An outage whose time was changed is reported the same way as a new one.

## Outage started or ended

`outage_now` becomes unavailable when a check fails and has no previous state after a restart,
so `on → off` alone misses restores. A trigger-based template binary sensor keeps the last known
state. It ignores `unavailable` and restores its state after a restart. Add it to
`configuration.yaml`:

```yaml
template:
  - triggers:
      - trigger: state
        entity_id: binary_sensor.zlatusha_outage_now
        to: ["on", "off"]
    binary_sensor:
      - name: Zlatusha power outage
        unique_id: zlatusha_power_outage_last_known
        state: "{{ trigger.to_state.state == 'on' }}"
```

Then trigger on that sensor:

```yaml
alias: Power outage started or ended
triggers:
  - trigger: state
    entity_id: binary_sensor.zlatusha_power_outage
    from: "off"
    to: "on"
    id: started
  - trigger: state
    entity_id: binary_sensor.zlatusha_power_outage
    from: "on"
    to: "off"
    id: ended
actions:
  - variables:
      expected_end: "{{ state_attr('binary_sensor.zlatusha_outage_now', 'expected_end') }}"
  - action: notify.mobile_app_phone
    data:
      title: "{{ 'Спрян ток' if trigger.id == 'started' else 'Токът е възстановен' }}"
      message: >-
        {% if trigger.id == 'started' %}Очаквано възстановяване: {{
          as_datetime(expected_end).strftime('%d.%m %H:%M') if expected_end else 'не е обявено'
        }}{% else %}{{ now().strftime('%d.%m %H:%M') }}{% endif %}
```

Registered outages are checked every 30 minutes, so a start or end can be noticed up to 30 minutes
late. By place, a planned outage starts and ends at the times of its schedule.

Entries without `outage_now` (ЕРМ Запад by place without a municipality, Електроразпределение Север)
have only planned outages. For them, use a calendar trigger with `event: start` and `event: end`
on `calendar.zlatusha_planned_outages`; their ends are always announced.

## Restore time announced

This automation fires when the operator announces or moves the restore time of the next or
current outage. It triggers on the `end` attribute of `next_outage` and checks that the outage is
the same one, with the same start and place.

```yaml
alias: Power restore time announced
triggers:
  - trigger: state
    entity_id: sensor.zlatusha_next_outage
    attribute: end
conditions:
  - condition: template
    value_template: >-
      {% set old = trigger.from_state %}
      {% set new = trigger.to_state %}
      {{ old is not none and new is not none
         and old.attributes.start is defined
         and old.attributes.start == new.attributes.start
         and old.attributes.place == new.attributes.place
         and new.attributes.end is not none }}
actions:
  - action: notify.mobile_app_phone
    data:
      title: >-
        {{ 'Обявено' if trigger.from_state.attributes.end is none else 'Променено' }}
        време за възстановяване на тока
      message: >-
        {{ as_datetime(trigger.to_state.attributes.end).strftime('%d.%m %H:%M') }}
```

Use `trigger.from_state.attributes.end is none` as an extra condition to be told only the first
time.

## Reminder before a planned outage

A calendar trigger with a negative offset fires that long before each outage that is known by
then. ЕРМ Запад announces outages for a client number only 48 hours ahead and its schedules by place
about two days ahead.

```yaml
alias: Power outage reminder
triggers:
  - trigger: calendar
    event: start
    entity_id: calendar.zlatusha_planned_outages
    offset: "-12:00:00"
conditions:
  # Planned outages only, not "possible disturbance" announcements.
  - condition: template
    value_template: "{{ trigger.calendar_event.summary.startswith('Планирано') }}"
actions:
  - variables:
      outage_start: "{{ as_datetime(trigger.calendar_event.start) | as_local }}"
      outage_end: "{{ as_datetime(trigger.calendar_event.end) | as_local }}"
      end_known: "{{ 'не е обявено' not in trigger.calendar_event.description }}"
  - action: notify.mobile_app_phone
    data:
      title: "{{ trigger.calendar_event.summary }}"
      message: |-
        {{ as_datetime(outage_start).strftime('%d.%m %H:%M') }}–{{
           as_datetime(outage_end).strftime('%H:%M') if end_known else '?' }}
        {{ trigger.calendar_event.location }}
```

When no end is announced, the calendar event ends at a placeholder one hour after its start, so
the example shows `?` instead.
