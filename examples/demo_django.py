"""Demo file exercising the Django 4.x -> 5.x plugin.

Run::

    pycomprepair scan examples/demo_django.py --target "django>=5.0"
    pycomprepair repair examples/demo_django.py --target "django>=5.0" --dry-run

Each block triggers a distinct rule from ``pycomprepair.plugins.django_v5``.
"""

from __future__ import annotations

# DJA001 — ``django.utils.timezone.utc`` was removed in Django 5.0.
from django.utils.timezone import utc

# DJA002 — ``smart_text`` was removed in favour of ``smart_str``.
from django.utils.encoding import smart_text

# DJA003 — ``ugettext_lazy`` was removed in favour of ``gettext_lazy``.
from django.utils.translation import ugettext_lazy as _


def label(value):
    return _("Value: {}").format(smart_text(value))


# DJA004 — ``Meta.index_together`` is deprecated.
class Article:
    class Meta:
        index_together = [["title", "slug"]]


__all__ = ["label", "utc"]
