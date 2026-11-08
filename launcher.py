"""Standalone local launcher for Nova Laser Quote."""
import os, webbrowser, threading, time
os.environ.setdefault("NOVA_HOST", "127.0.0.1")
os.environ.setdefault("NOVA_PORT", "8081")
from waitress import serve
from app import app
if __name__ == "__main__":
    port=int(os.environ["NOVA_PORT"])
    print(f"Nova Laser Quote: http://127.0.0.1:{port}")
    threading.Thread(target=lambda: (time.sleep(1.5), webbrowser.open(f"http://127.0.0.1:{port}")), daemon=True).start()
    serve(app, host=os.environ["NOVA_HOST"], port=port, threads=6)
