"""ZipZy DBA connector.

Runs inside the customer's network. It reads connector.yaml, reaches the databases listed
there with a read-only monitoring user, and only ever dials OUT to ZipZy. Database passwords
never leave this program.
"""

__version__ = "0.2.0"
