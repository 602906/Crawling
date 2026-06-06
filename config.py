import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")
HOST = "0.0.0.0"
PORT = 8000

os.makedirs(DOWNLOAD_DIR, exist_ok=True)
