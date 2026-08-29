import os

from dotenv import load_dotenv

load_dotenv()

from mcorsi import create_app


app = create_app(os.environ.get("MCORSI_ENV", "production"))


if __name__ == "__main__":
    app.run(
        host=os.environ.get("MCORSI_HOST", "127.0.0.1"),
        port=int(os.environ.get("MCORSI_PORT", "5100")),
        debug=False,
    )
