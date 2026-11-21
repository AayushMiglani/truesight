import sys

from truesight.agent import investigate


def main(argv: list[str] | None = None) -> None:
    if argv is None:
        argv = sys.argv
    if len(argv) < 2:
        print("usage: python -m truesight")
        return
    print(investigate(" ".join(argv[1:])))


if __name__ == "__main__":
    main()
