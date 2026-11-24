# Render the changed parts of an attendance page without reloading its layout.
from hashlib import sha256

from django.http import HttpResponseNotModified, JsonResponse
from django.template.loader import render_to_string
from django.utils.http import parse_etags, quote_etag


def live_attendance_response(request, context, templates):
    fragments = {
        name: render_to_string(template, context, request)
        for name, template in templates.items()
    }
    response = JsonResponse(fragments)
    etag = quote_etag(sha256(response.content).hexdigest())
    # A visible list checks often, so send only headers when its contents match.
    if etag in parse_etags(request.headers.get("If-None-Match", "")):
        response = HttpResponseNotModified()
    response["ETag"] = etag
    return response
