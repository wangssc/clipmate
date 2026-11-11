"""ClipMate 粘贴助手 —— 双击这个文件（或旁边的 vbs）启动。

不联网、不写注册表、数据都在同目录 data 文件夹里。
"""

import os
import sys
import traceback

BASE = os.path.dirname(os.path.abspath(__file__))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

if __name__ == "__main__":
    try:
        from clipmate.main import main

        main()
    except Exception:
        # 不弹任何错误框：能写日志就写日志，写不了就落一个 crash.txt
        detail = traceback.format_exc()
        logged = False
        try:
            from clipmate import paths

            paths.setup_logging().error("启动失败\n%s", detail)
            logged = True
        except Exception:
            pass
        if not logged:
            try:
                crash = os.path.join(BASE, "data", "crash.txt")
                os.makedirs(os.path.dirname(crash), exist_ok=True)
                with open(crash, "a", encoding="utf-8") as f:
                    f.write(detail + "\n")
            except Exception:
                pass
        if sys.stderr is not None:
            sys.stderr.write(detail)
        raise
