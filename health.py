"""The bot's small web server, which the update system depends on.
PROTECTED: see PROTECTED.md. A change here could stop the update system
from telling whether a new version came up, and so from rolling it back.

- GET /healthz answers 200 once connected to Discord, and 503 before.
  Railway waits for it before sending traffic to a new version, and the
  self-update workflow reads `commit` from it to confirm what is live.
- GET /api/passed lists the proposals that passed, or that an admin
  shipped without a vote, and may need a code change. The self-update workflow reads it. Everything in it is already
  public in #proposals.

Railway sets PORT; without it (running locally) nothing is served.
"""

import logging
import os

from aiohttp import web

import proposals

log = logging.getLogger("health")

COMMIT = (os.environ.get("RAILWAY_GIT_COMMIT_SHA") or "local")[:7]


def passed_proposals():
    """Passed general proposals, oldest first, as the workflow needs them."""
    found = [p for p in proposals.all_proposals()
             if p["kind"] == proposals.GENERAL and p["status"] == proposals.PASSED]
    found.sort(key=lambda p: p["no"])
    return [{"no": p["no"], "title": p["title"], "details": p["details"],
             "shipped": bool(p.get("shipped_by"))} for p in found]


async def serve(client):
    port = os.environ.get("PORT")
    if not port:
        return

    async def healthz(request):
        ready = client.is_ready()
        return web.json_response(
            {"ready": ready, "commit": COMMIT,
             "started": client.started_at.isoformat()},
            status=200 if ready else 503,
        )

    async def passed(request):
        return web.json_response(passed_proposals())

    app = web.Application()
    app.router.add_get("/healthz", healthz)
    app.router.add_get("/api/passed", passed)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", int(port)).start()
    log.info(f"serving /healthz and /api/passed on :{port}")
