import os

# Required settings must exist before lazy_termin.config is imported.
os.environ.setdefault("DEBUG", "True")
os.environ.setdefault("MAXIMUM_ENTRIES", "10")
os.environ.setdefault("ADMIN_ID", "1")
