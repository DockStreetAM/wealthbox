wealthbox
=========

Python wrapper for the `Wealthbox CRM API <https://dev.wealthbox.com/>`_.

Install
-------

.. code-block:: bash

    pip install wealthbox          # library only
    pip install "wealthbox[cli]"   # library + the ``wb`` command line tool

Get an API token from WealthBox: Settings → API Access.

Library usage
-------------

.. code-block:: python

    import os
    from wealthbox import WealthBox

    wb = WealthBox(token=os.environ["WEALTHBOX_ACCESS_TOKEN"])
    contacts = wb.get_contacts({"type": "Person"})

The library never looks for a token itself — it does not read
``WEALTHBOX_ACCESS_TOKEN`` or any ``.env`` file. Load the token however
you like and pass it as ``token=``. A missing or wrong token shows up as a
``WealthBoxAPIError`` with status 401/403 that says so.

Command line (``wb``)
---------------------

Save your token once, in a regular terminal:

.. code-block:: bash

    wb auth set-token        # prompts with hidden input
    wb auth test             # -> Authenticated as: <your name>

``wb`` looks for the token in this order:

1. the ``WEALTHBOX_ACCESS_TOKEN`` environment variable
2. a file you name with ``wb --env-file PATH ...``
3. ``~/.config/wealthbox/credentials.json`` (written by ``wb auth set-token``, owner-only)
4. ``~/.config/wealthbox/.env``

If there's no terminal to prompt in (scripts, editors, AI agents), use
``wb auth set-token --from-env PATH`` or pipe the token into
``wb auth set-token -``.

Upgrading to 0.18
~~~~~~~~~~~~~~~~~

Before 0.18.0, ``wb`` also read a ``.env`` file in the **current
directory**. It no longer does, because a cloned project's ``.env`` could
silently point ``wb`` at a different WealthBox workspace. If you kept your
token in a project ``.env``, ``wb`` will now say it can't find a token
(and point at that file). Fix it once with:

.. code-block:: bash

    wb auth set-token --from-env .env

or keep using the file explicitly with ``wb --env-file .env ...``.
The library itself is unaffected; it never read ``.env`` files.

See ``CHANGELOG.md`` for the other behavior changes in 0.18.0.

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

Update the version in ``pyproject.toml``, commit, then push a tag
``vX.Y.Z`` matching that version. GitHub Actions runs the tests, checks
the tag matches ``pyproject.toml``, and publishes to PyPI via Trusted
Publishing (no stored token).
