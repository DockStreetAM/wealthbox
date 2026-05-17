wealthbox
=========

Python wrapper for the `Wealthbox CRM API <https://dev.wealthbox.com/>`_.

Usage
-----

.. code-block:: python

    from wealthbox import WealthBox

    wb = WealthBox(token="your_access_token")
    contacts = wb.get_contacts({"type": "Person"})

Filtering
~~~~~~~~~

Filter dicts are passed straight through to the API as query parameters.
List/tuple values are auto-converted to ``key[]=v1&key[]=v2`` bracket
syntax, which the Wealthbox API treats as OR-filtering for fields
documented as ``array[string]`` (e.g. ``tags`` on ``/contacts``).

.. code-block:: python

    # OR-filter by tag — returns contacts having EITHER tag
    wb.get_contacts({"tags": ["VIP", "Top 10"]})

For fields documented as scalar ``string`` (e.g. ``contact_type``,
``type``), the API does not support multi-value filtering at all and will
return HTTP 500 if a list is passed. Fan out client-side instead:

.. code-block:: python

    seen, out = set(), []
    for ct in ("Client", "Trustee"):
        for c in wb.get_contacts({"type": "Person", "contact_type": ct}):
            if c["id"] not in seen:
                seen.add(c["id"])
                out.append(c)

This caveat exists because Wealthbox's API takes only the *last* value of
repeated query params (``?k=a&k=b`` → ``b`` wins), which is what
``requests`` produces by default for list values. The bracket rewrite in
``api_request`` makes documented array filters work as expected.

Publishing
----------

To publish, first update ``pyproject.toml`` with the new version number,
then create a new release with the tag ``vx.y.z``.
