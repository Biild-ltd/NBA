from fastapi import APIRouter

from app.constants.branches import NBA_BRANCHES

router = APIRouter(tags=["Utility"])


@router.get("/healthz", summary="Health check")
async def health_check() -> dict:
    """Returns 200 OK when the service is running.

    Used by Cloud Build smoke tests, Cloud Run health probes, and
    Cloud Monitoring uptime checks.
    """
    return {"status": "ok"}


@router.get("/branches", summary="List NBA branches")
async def list_branches() -> dict:
    """Return the complete list of valid NBA branch names.

    Used by the frontend to populate the branch selector and by the
    backend to validate the `branch` field on profile creation.
    """
    return {"branches": NBA_BRANCHES}
