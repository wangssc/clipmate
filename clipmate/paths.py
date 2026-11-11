"""路径与日志：所有数据都落在程序目录下，不写别处、不联网。"""

import logging
import logging.handlers
import os
import sys

if getattr(sys, "frozen", False):
    # 打包成 exe 后：__file__ 在临时解包目录，必须用 exe 自己所在的目录
    APP_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(APP_DIR, "data")

# 自测用：允许把数据目录指到项目内的临时沙箱，绝不指到项目外面
_override = os.environ.get("CLIPMATE_DATA_DIR")
if _override:
    _abs = os.path.abspath(_override)
    if _abs.startswith(APP_DIR + os.sep):
        DATA_DIR = _abs

SNIPPETS_FILE = os.path.join(DATA_DIR, "snippets.json")
HISTORY_FILE = os.path.join(DATA_DIR, "history.json")
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
LOG_FILE = os.path.join(DATA_DIR, "clipmate.log")
ICON_FILE = os.path.join(APP_DIR, "app.ico")


def ensure_dirs():
    os.makedirs(DATA_DIR, exist_ok=True)


def setup_logging():
    ensure_dirs()
    logger = logging.getLogger("clipmate")
    if logger.handlers:
        return logger
    logger.setLevel(logging.DEBUG)
    handler = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=512 * 1024, backupCount=2, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(threadName)s %(message)s")
    )
    logger.addHandler(handler)
    logger.propagate = False
    return logger
