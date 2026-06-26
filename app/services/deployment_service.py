"""Deployment service — create, close, and track location history for traps.

All functions assume an active SQLAlchemy session (they add/flush but never
commit). The caller owns the transaction boundaries.
"""
import logging

from app.models.database import db
from app.models.deployment import Deployment
from app.models.deployment_location import DeploymentLocation

logger = logging.getLogger("app.deployment_service")


def create_deployment(trap, location=None, notes=None):
    """Create a new active deployment for *trap*.

    Any existing active deployment is closed first (at-most-one-active
    invariant). If *location* is provided, an initial location entry is
    recorded under the new deployment.
    """
    close_active_deployment(trap)

    deployment = Deployment(
        trap_id=trap.id,
        status="active",
        notes=notes,
    )
    db.session.add(deployment)
    db.session.flush()  # obtain the auto-generated deployment.id

    if location is not None:
        db.session.add(
            DeploymentLocation(
                deployment_id=deployment.id,
                location=location,
            )
        )

    logger.info(
        "Created deployment #%d for trap #%d (%s)",
        deployment.id,
        trap.id,
        trap.trap_id,
    )
    return deployment


def close_active_deployment(trap):
    """Close the current active deployment for *trap*, if one exists.

    Returns the deployment that was closed, or None.
    """
    active = trap.get_active_deployment()
    if active is None:
        return None
    active.close()
    logger.info(
        "Closed deployment #%d for trap #%d (%s)",
        active.id,
        trap.id,
        trap.trap_id,
    )
    return active


def record_location_change(trap, new_location, notes=None):
    """Record *new_location* under the trap's active deployment.

    Returns the new DeploymentLocation, or None when there is no active
    deployment or no meaningful location to record.
    """
    if not new_location:
        return None

    active = trap.get_active_deployment()
    if active is None:
        logger.warning(
            "Location change on trap #%d (%s) but no active deployment",
            trap.id,
            trap.trap_id,
        )
        return None

    loc = DeploymentLocation(
        deployment_id=active.id,
        location=new_location,
        notes=notes,
    )
    db.session.add(loc)
    logger.info(
        "Recorded location '%s' in deployment #%d for trap #%d (%s)",
        new_location,
        active.id,
        trap.id,
        trap.trap_id,
    )
    return loc


def get_location_history(trap):
    """Return all location entries for a trap across all deployments."""
    stmt = (
        db.select(DeploymentLocation)
        .join(Deployment, DeploymentLocation.deployment_id == Deployment.id)
        .where(Deployment.trap_id == trap.id)
        .order_by(DeploymentLocation.recorded_at.desc())
    )
    return db.session.execute(stmt).scalars().all()
