import logging
import sys

# logging.SafeRotatingFileHandler = SafeRotatingFileHandler
# log_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'configlog.ini')
# logging.config.fileConfig(log_file_path)


def new_hook(t, v, tb):
    # 如果异常类型是 KeyboardInterrupt
    if issubclass(t, KeyboardInterrupt):
        # 使用默认的异常处理函数处理 KeyboardInterrupt 异常
        sys.__excepthook__(t, v, tb)
        # 返回，不再执行后续操作
        return
    # 使用 logging 模块记录未捕获的异常信息
    logging.getLogger('biliup').error("Uncaught exception:", exc_info=(t, v, tb))

# 将 sys.excepthook 替换为自定义的异常处理函数 new_hook
sys.excepthook = new_hook


