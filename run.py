"""Point d'entrée : lance le serveur Flask de développement."""
from app.factory import create_app

if __name__ == "__main__":
    app = create_app()
    app.run(host="127.0.0.1", port=5000, debug=True)