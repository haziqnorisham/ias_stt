"""Flask CLI commands for managing local users."""
import click
from sqlalchemy import func

from app.auth import VALID_ROLES
from app.models.database import db
from app.models.user import User


def register_cli(app):
    @app.cli.command("create-user")
    @click.argument("username")
    @click.option("--role", type=click.Choice(VALID_ROLES), required=True)
    @click.option("--display-name", default=None)
    @click.option("--email", default=None)
    @click.option(
        "--password",
        prompt=True,
        hide_input=True,
        confirmation_prompt=True,
    )
    def create_user(username, role, display_name, email, password):
        """Create or update a local JWT user."""
        existing = User.query.filter(
            func.lower(User.username) == username.strip().lower()
        ).first()
        if existing is not None and existing.auth_provider != "LOCAL":
            raise click.ClickException(
                "This username belongs to an LDAP account; the CLI only manages LOCAL users."
            )

        user = existing or User(username=username.strip(), auth_provider="LOCAL")
        if (
            existing is not None
            and existing.auth_provider == "LOCAL"
            and existing.is_active
            and existing.role == "administrator"
            and role != "administrator"
            and User.query.filter_by(
                auth_provider="LOCAL",
                role="administrator",
                is_active=True,
            ).filter(User.id != existing.id).count() == 0
        ):
            raise click.ClickException(
                "At least one enabled LOCAL administrator must remain."
            )
        user.role = role
        user.display_name = display_name
        user.email = email
        user.is_active = True
        user.set_password(password)
        if existing is not None:
            # A password is supplied on every CLI run, so invalidate previous
            # access and refresh tokens after credential maintenance.
            user.token_version += 1
        db.session.add(user)
        db.session.commit()
        click.echo(f"User {username} is ready with role {role}.")
