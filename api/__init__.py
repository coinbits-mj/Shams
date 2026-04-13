from __future__ import annotations
from flask import Flask


def register_blueprints(app: Flask) -> None:
    from api.auth import bp as auth_bp
    from api.chat import bp as chat_bp
    from api.projects import bp as projects_bp
    from api.agents import bp as agents_bp
    from api.mercury import bp as mercury_bp
    from api.integrations import bp as integrations_bp
    from api.actions import bp as actions_bp
    from api.inbox import bp as inbox_bp
    from api.files import bp as files_bp
    from api.briefings import bp as briefings_bp
    from api.settings import bp as settings_bp
    from api.deals import bp as deals_bp
    from api.signatures import bp as signatures_bp
    from api.money import bp as money_bp
    from api.bridge import bp as bridge_bp

    for blueprint in [
        auth_bp, chat_bp, projects_bp, agents_bp, mercury_bp,
        integrations_bp, actions_bp, inbox_bp, files_bp, briefings_bp,
        settings_bp, deals_bp, signatures_bp, money_bp, bridge_bp,
    ]:
        app.register_blueprint(blueprint)
