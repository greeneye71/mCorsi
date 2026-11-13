from dotenv import load_dotenv

from mcorsi.startup_secrets import resolve_env_path

load_dotenv(resolve_env_path())

from mcorsi.mcp_server import run


if __name__ == "__main__":
    run()
