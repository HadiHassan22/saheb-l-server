"""Proposals to change one of the bot's settings (settings.py), from
/propose-setting or a draft in #ask-saheb. The new value is checked
against the setting's fixed range when proposed, and applied by code the
moment the proposal passes, by vote or by an admin. #welcome quotes the
settings, so it is brought up to date too.
"""

import logging

import kinds
import layout
import proposals
import settings

log = logging.getLogger("setting_changes")


def problem(setting, value):
    """Why `setting` can't be proposed as `value`, or None."""
    wrong = settings.check(setting, value)
    if wrong:
        return wrong[0].upper() + wrong[1:] + "."
    if settings.current()[setting] == value:
        return (f"{settings.SETTINGS[setting]['label']} is already "
                f"{settings.describe(setting, value)}.")
    return None


def title(setting, value):
    return f"{settings.SETTINGS[setting]['label']}: {settings.describe(setting, value)}"


def _now_is(p):
    return (f"{settings.SETTINGS[p['setting']]['label']} is now "
            f"{settings.describe(p['setting'], p['value'])}.")


class SettingChange(kinds.Kind):
    def open(self, author_id, setting, value, reason, now):
        wrong = problem(setting, value)
        if wrong:
            raise proposals.Refused(wrong)
        label = settings.SETTINGS[setting]["label"]
        details = (f"Change {label.lower()} from "
                   f"{settings.describe(setting, settings.current()[setting])} to "
                   f"{settings.describe(setting, value)}."
                   + (f"\n\n{reason.strip()}" if reason.strip() else ""))
        return proposals.file(author_id, proposals.SETTING, title(setting, value), details,
                              now, setting=setting, value=value)

    def open_draft(self, author_id, draft, now):
        payload = draft["payload"]
        return self.open(author_id, payload["setting"], payload["value"],
                         payload.get("reason", ""), now)

    async def carry_out(self, client, guild, p):
        try:
            settings.apply(p["setting"], p["value"])
        except ValueError as e:
            return f"It couldn't be applied: {e}."
        if guild is not None:
            try:
                await layout.post_texts(guild)  # #welcome quotes the settings
            except Exception as e:
                log.warning(f"#welcome wasn't updated after proposal {p['no']}: {e!r}")
        return _now_is(p)


KIND = kinds.register(proposals.SETTING, SettingChange())
