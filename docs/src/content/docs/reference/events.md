---
title: Events
id: DOC-REF-EVENTS-001
type: Reference
status: Active
updated: "2026-08-22"
summary: "The facts this studio publishes on the platform event bus: one row per type under the platform domain it owns, with the subject and the pointers each carries. The consumer's contract, held equal to the publisher by a test."
---

The studio owns the `platform` domain on the event bus by its own grant (the platform's `onboard-events` guide), and publishes one fact per act that changes what an install runs. This page is the contract a consumer reads: the types, what each is about, and what `data` carries. It is held equal to the publisher's constants by the backend suite (`test_event_publishing.py`), so a row here is a type the studio emits and nothing else is.

Every event is a CloudEvent with `source` `/foundry/platform-studio` and `datacontenttype` `application/json`. Each carries identity and pointers, never a rendered file or a report body: a consumer treats the event as a hint and reads the install's deploy branch, the pull request, or the conformance report for the truth. Publishing is one-way (`REF-Events` section 6): a publish that cannot be delivered is dropped and logged, and the act completes unchanged, which `INT-EVENTS-001` attests for every act below.

## The types

| Type | `subject` | Published when | `data` |
|---|---|---|---|
| `com.foundry.platform.app.onboarded` | the app | an app's onboarding pull request opens against the install's branch | `app`, `branch`, `pr` (URL) |
| `com.foundry.platform.app.offboarded` | the app | an app's offboarding pull request opens | `app`, `branch`, `pr` (URL) |
| `com.foundry.platform.grant.issued` | the app | a capability grant's pull request opens for an app | `app`, `capability` (`database`, `identity`, `events`), `branch`, `pr` (URL) |
| `com.foundry.platform.app.paused` | the app | an app is scaled to zero on the install's branch | `app` |
| `com.foundry.platform.app.resumed` | the app | an app's scale-to-zero is lifted | `app` |
| `com.foundry.platform.promotion.frozen` | the app | an app is held on the version it runs | `app` |
| `com.foundry.platform.promotion.resumed` | the app | the hold on an app's version is lifted | `app` |
| `com.foundry.platform.change.opened` | the app, or the setting key | any conformance-gated pull request opens against the install's branch, whichever act opened it | `subject`, `branch`, `pr` (URL), `title`, `changed_files` (count) |
| `com.foundry.platform.setting.changed` | the setting key | a platform setting's pull request opens | `setting`, `value`, `previous`, `branch`, `pr` (URL) |
| `com.foundry.platform.conformance.completed` | the install | a conformance run finishes | `passed`, `failed`, `skipped`, `verdict` (`pass` or `fail`) |

## What is not stated

A toggle that changes nothing (pausing a paused app, freezing a frozen one) states nothing: an event is a past-tense statement of something that happened. The gated acts state `change.opened` first and their own fact second, so a consumer waiting on "a change awaits admission" subscribes to one type, and one reacting to a specific act subscribes to that act's.

Adding a type is one change to this page and to `event_types.py` together; the test refuses either alone.
