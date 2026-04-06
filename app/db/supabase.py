from supabase import create_client, Client
from app.config import settings

_anon_client: Client | None = None
_service_client: Client | None = None


def get_anon_client() -> Client:
    """Return the Supabase client initialised with the anon key.

    Respects Row Level Security — use for operations scoped to the
    authenticated user (e.g. Supabase Auth sign-up / login calls).
    """
    global _anon_client
    if _anon_client is None:
        _anon_client = create_client(settings.SUPABASE_URL, settings.SUPABASE_ANON_KEY)
    return _anon_client


def get_service_client() -> Client:
    """Return the Supabase client initialised with the service role key.

    Bypasses Row Level Security — use for all server-side database
    operations (profile CRUD, payment records, admin queries).
    Never expose this client or its key to the frontend.
    """
    global _service_client
    if _service_client is None:
        _service_client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)
    return _service_client
