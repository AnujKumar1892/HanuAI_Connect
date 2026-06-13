import re
from django.conf import settings


class SessionTagMiddleware:
    """
    Enables multiple simultaneous sessions in different browser tabs.
    Append ?_st=<tag> to the URL to use a separate session cookie namespace.
    Each tag gets its own sessionid_<tag> and csrftoken_<tag> cookies.

    Uses save-and-restore on settings to avoid global state leaking between requests.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        st = (request.GET.get('_st') or
              request.POST.get('_st') or
              request.META.get('HTTP_X_SESSION_TAG', '').strip())

        if st and re.match(r'^[a-zA-Z0-9_-]{1,32}$', st):
            request._st = st

            # Save old cookie names to restore after the response
            request._old_session_cookie = settings.SESSION_COOKIE_NAME
            request._old_csrf_cookie = settings.CSRF_COOKIE_NAME

            # Set tagged names for this request's lifecycle
            settings.SESSION_COOKIE_NAME = f'{settings.SESSION_COOKIE_NAME}_{st}'
            settings.CSRF_COOKIE_NAME = f'{settings.CSRF_COOKIE_NAME}_{st}'

        response = self.get_response(request)

        if hasattr(request, '_st'):
            # Restore global settings so the next request without _st works
            settings.SESSION_COOKIE_NAME = request._old_session_cookie
            settings.CSRF_COOKIE_NAME = request._old_csrf_cookie

            # Preserve _st in redirect URLs (e.g. @login_required redirect)
            if response.status_code in (301, 302, 303):
                location = response.get('Location', '')
                if location and not location.startswith('http') and '_st=' not in location:
                    sep = '&' if '?' in location else '?'
                    response['Location'] = f'{location}{sep}_st={request._st}'

        return response
