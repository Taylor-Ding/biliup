import logging
import platform
import sys

__version__ = "0.4.78"

LOG_CONF = {
    # 日志配置版本
    'version': 1,
    # 格式化配置
    'formatters': {
        # 详细格式
        'verbose': {
            # 格式字符串，包含时间、文件名、行号、进程ID、线程名、日志级别和消息内容
            'format': "%(asctime)s %(filename)s[line:%(lineno)d](Pid:%(process)d "
                      "Tname:%(threadName)s) %(levelname)s %(message)s",
            # 注释掉的日期格式字符串，未使用
            # 'datefmt': "%Y-%m-%d %H:%M:%S"
        },
        # 简单格式
        'simple': {
            # 格式字符串，包含时间、文件名、行号、日志级别、线程名和消息内容
            'format': '%(asctime)s %(filename)s%(lineno)d[%(levelname)s]Tname:%(threadName)s %(message)s'
        },
    },
    # 处理器配置
    'handlers': {
        # 控制台处理器
        'console': {
            # 日志级别
            'level': logging.DEBUG,
            # 处理器类
            'class': 'logging.StreamHandler',
            # 输出流
            'stream': sys.stdout,
            # 使用的格式化器
            'formatter': 'simple'
        },
        # 文件处理器
        'file': {
            # 日志级别
            'level': logging.DEBUG,
            # 处理器类
            'class': 'biliup.common.log.SafeRotatingFileHandler',
            # 何时滚动日志文件
            'when': 'W0',
            # 滚动的间隔
            'interval': 1,
            # 保留的备份文件数
            'backupCount': 1,
            # 日志文件名
            'filename': 'ds_update.log',
            # 使用的格式化器
            'formatter': 'verbose',
            # 文件编码
            'encoding': 'utf-8'
        }
    },
    # 根日志配置
    'root': {
        # 使用的处理器
        'handlers': ['console'],
        # 日志级别
        'level': logging.INFO,
    },
    # 日志器配置
    'loggers': {
        # biliup日志器
        'biliup': {
            # 使用的处理器
            'handlers': ['file'],
            # 日志级别
            'level': logging.INFO,
        },
    }
}


if (3, 10, 6) > sys.version_info >= (3, 8) and platform.system() == 'Windows':
    # 如果Python版本在3.8到3.10.6之间，并且操作系统是Windows
    # 修复Windows中的'Event loop is closed' RuntimeError
    # fix 'Event loop is closed' RuntimeError in Windows
    from asyncio import proactor_events
    from biliup.common.tools import silence_event_loop_closed

    # 将_ProactorBasePipeTransport类的析构函数替换为经过silence_event_loop_closed处理的析构函数
    # 这样可以在析构时忽略'Event loop is closed'的错误
    proactor_events._ProactorBasePipeTransport.__del__ = silence_event_loop_closed(
        proactor_events._ProactorBasePipeTransport.__del__)



if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
    # 如果系统被冻结（即使用PyInstaller打包），并且存在_MEIPASS属性
    import multiprocessing
    # 导入multiprocessing模块
    multiprocessing.freeze_support()
    # 调用multiprocessing模块的freeze_support函数，以支持在冻结的环境中使用多进程
    print('running in a PyInstaller bundle')
