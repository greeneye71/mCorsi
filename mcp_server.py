from envfile import load_env_file

load_env_file()

from mcorsi.mcp_server import run  # noqa: E402

if __name__ == "__main__":
    run()
