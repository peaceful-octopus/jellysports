import os
import traceback


class otype:
    ERROR = '-'
    DEBUG = '*'
    REGULAR = '+'


class colours:
    HEADER = '\033[95m' if os.name != 'nt' else ""
    OKBLUE = '\033[94m' if os.name != 'nt' else ""
    OKCYAN = '\033[96m' if os.name != 'nt' else ""
    OKGREEN = '\033[92m' if os.name != 'nt' else ""
    WARNING = '\033[93m' if os.name != 'nt' else ""
    FAIL = '\033[91m' if os.name != 'nt' else ""
    ENDC = '\033[0m' if os.name != 'nt' else ""
    BOLD = '\033[1m' if os.name != 'nt' else ""
    UNDERLINE = '\033[4m' if os.name != 'nt' else ""


def check_verbosity(t: str = otype.DEBUG):
    """Debug messages print only with -v; everything is silenced by quiet mode except errors."""
    verbosity = os.environ.get("verbosity")
    no_verbosity = os.environ.get("no_verbosity")
    return (not (t == otype.DEBUG and verbosity == "1") and no_verbosity == "1") or t == otype.ERROR


def p(s, c: str = "", t: str = otype.DEBUG, err: Exception = None) -> None:
    if check_verbosity(t):
        print(f"{c}[{t}]{colours.ENDC} {s}", flush=True)
    if err and os.environ.get("verbosity") == "0" and os.environ.get("no_verbosity") != "0":
        traceback.print_exception(type(err), err, err.__traceback__)


def pind(s, c: str = "", t: str = otype.DEBUG) -> None:
    if check_verbosity(t):
        print(f"{c}---> [{t}]{colours.ENDC} {s}", flush=True)


def pind2(s, c: str = "", t: str = otype.DEBUG) -> None:
    if check_verbosity(t):
        print(f"{c}------> [{t}]{colours.ENDC} {s}", flush=True)
