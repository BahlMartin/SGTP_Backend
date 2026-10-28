# app/middlewares/ws_auth.py
from urllib.parse import parse_qs
from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.models import Session
from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection

User = get_user_model()

@database_sync_to_async
def get_user_from_session(session_key):
    close_old_connections()
    try:
        session = Session.objects.get(session_key=session_key)
        user_id = session.get_decoded().get('_auth_user_id')
        return User.objects.get(pk=user_id)
    except Exception:
        return AnonymousUser()
    finally:
        connection.close()

class QueryStringAuthMiddleware:
    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        scope = dict(scope)
        query_string = scope.get('query_string', b'').decode('utf-8')
        query_params = parse_qs(query_string)
        
        # Busca 'token' O 'sessionid' en la URL
        token_list = query_params.get('token') or query_params.get('sessionid')
        session_key = token_list[0] if token_list else None

        if session_key:
            user = await get_user_from_session(session_key)
            if user and user.is_authenticated:
                scope['user'] = user
            
        return await self.inner(scope, receive, send)
