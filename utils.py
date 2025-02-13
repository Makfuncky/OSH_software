import os
from flask import current_app

def get_file_path(filename):
    try:
        root_path = current_app.root_path
    except RuntimeError:
        # No app context is available; fall back to using the directory of this file
        # (Adjust this if your 'database' folder is elsewhere)
        root_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(root_path, 'database', filename)
