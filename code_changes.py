"""General proposals: anything members want that no other kind of proposal
covers, like a new feature or a change to how the bot works. When one
passes, by vote or by an admin, the self-update workflow writes it as a
code change: the bot starts the workflow at once, health.py lists the
proposal at /api/passed for it, and updates.py reports its progress under
its card.
"""

import kinds
import proposals
import updates


class CodeChange(kinds.Kind):
    shipped_footer = ("The code change still goes through every automatic check, and "
                      "progress is posted here.")

    def open(self, author_id, title, details, now):
        return proposals.file(author_id, proposals.GENERAL, title.strip(), details.strip(),
                              now)

    def open_draft(self, author_id, draft, now):
        return self.open(author_id, draft["title"], draft["details"], now)

    async def carry_out(self, client, guild, p):
        updates.start_soon(guild, p["no"])
        return ("It will now be written as a code change, checked, and deployed "
                "automatically. Progress will be posted here.")


KIND = kinds.register(proposals.GENERAL, CodeChange())
