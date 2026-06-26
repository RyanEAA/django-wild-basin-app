from django import template

register = template.Library()


@register.simple_tag
def url_replace(request, field, value):
    """Return encoded querystring with `field` set to `value`.

    If `value` is None the field will be removed.
    """
    querydict = request.GET.copy()
    if value is None:
        querydict.pop(field, None)
    else:
        querydict[field] = value
    return querydict.urlencode()
