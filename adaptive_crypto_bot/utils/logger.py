import logging, sys

class _ColorFormatter(logging.Formatter):
    COLORS = {
        logging.DEBUG: "\033[90m",
        logging.INFO:  "\033[37m",
        logging.WARNING:"\033[33m",
        logging.ERROR: "\033[31m",
        logging.CRITICAL:"\033[41m",
    }
    RESET = "\033[0m"

    def format(self, record):
        prefix = self.COLORS.get(record.levelno, "")
        record.msg = f"{prefix}{record.msg}{self.RESET}"
        return super().format(record)

def setup(level="INFO"):
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(_ColorFormatter("%(asctime)s  %(levelname)-8s %(name)s ▶ %(message)s"))
    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(h)
