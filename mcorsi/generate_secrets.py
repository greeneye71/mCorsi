from __future__ import annotations

from .services.secrets import generate_secret_values


def main() -> None:
    for name, value in generate_secret_values().items():
        print(f"{name}={value}")


if __name__ == "__main__":
    main()
