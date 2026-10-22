# RemindMe Product Documentation

## Table of Contents
1. Author
2. Revision History
3. Description
4. Product Overview
5. Reminder Channels
6. Reminder Escalation Model
7. Account and Event Data
8. Safety and Consent Features
9. Reliability and Observability
10. Administrative Controls

## Author
RemindMe Product and Engineering, approved by the CEO.

## Revision History
| Version | Date | Owner | Notes |
| --- | --- | --- | --- |
| 1.0 | 2026-10-17 | Product Team | Initial product documentation manual. |

## Description
RemindMe is custom alarm and alerting software built to help users remember critical events. The product allows users to create events, choose reminder channels, configure escalation behavior, and involve trusted people when a simple alarm may not be enough.

This document describes the product from an internal operating perspective. It should guide Product, Engineering, Design, Support, Sales, Compliance, and Operations when discussing how RemindMe works.

## Product Overview
A RemindMe event is a scheduled item with a title, time, time zone, reminder plan, notification channels, escalation rules, and optional trusted contacts. Events may be one-time or recurring. Users can create events for appointments, deadlines, travel, personal commitments, caregiving tasks, medication, bills, meetings, interviews, and other important moments.

The product goal is not simply to make noise. The goal is to increase the chance that the right person takes the right action at the right time. This means RemindMe must consider channel reliability, user attention, privacy, fatigue, and human backup.

## Reminder Channels
RemindMe supports four primary reminder categories.

Phone alarms alert the user's own device through push notifications, audible alarms, vibration, and repeated prompts where supported. Users should be able to set timing, sound, snooze behavior, and acknowledgement requirements.

Social media reminders allow the user to approve a post or message that asks their network to remind them. This is useful for users who respond to social accountability, but it requires strong previews, warnings, and privacy controls.

Friend or coworker outreach asks a selected person to call or text the user. This feature should include contact enrollment, message templates, opt-out controls, quiet hours, and escalation limits.

Close-relative physical contact requests ask a trusted person to make direct contact with the user, such as knocking on a door or checking in personally. This feature must be framed as a voluntary request and must not imply emergency dispatch.

## Reminder Escalation Model
A reminder plan may include multiple steps. For example, a user might receive a phone alarm thirty minutes before an event, another alarm ten minutes before, a text request to a coworker at the event time if unacknowledged, and a relative contact request five minutes later.

Escalation should be based on clear triggers such as no acknowledgement, failed delivery, user-selected timing, or manual activation. The system should prevent unlimited escalation loops. Users must be able to cancel, pause, or edit reminders before escalation occurs where practical.

## Safety and Consent Features
RemindMe should include consent prompts, contact opt-outs, abuse reporting, rate limits, content warnings, and audit logs. Contacts should know who requested their involvement and how to stop future requests. Users should know when a contact has declined or opted out.

The product should block or review patterns that suggest harassment, unwanted contact, public shaming, impersonation, or coercion. High-risk features should include Trust and Safety visibility and administrative controls for suspension.

## Reliability and Observability
Reminder reliability depends on scheduling accuracy, queue health, notification provider status, carrier and platform delivery, user device settings, and contact availability. Engineering should maintain monitoring for scheduled job delays, failed notifications, provider errors, unusual retry volumes, and time zone anomalies.

## Administrative Controls
Internal tools should allow authorized staff to inspect delivery status, respond to support issues, disable abusive reminders, honor opt-outs, and investigate incidents. Administrative access must be role-based, logged, and reviewed. Manual interventions should preserve user privacy and be documented with a business reason.
