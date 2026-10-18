"""Build edition switch.

* ``full``       - the repository / the developer's own platform (default).
* ``standalone`` - a customer release (``make release``). The release build overwrites this file.
                   Such a build can never run as a platform and always verifies its license against
                   the address baked in below, whatever the customer puts in their ``.env``.
"""
EDITION = "full"
LOCKED_LICENSE_SERVER_URL = ""
VERSION = "dev"
