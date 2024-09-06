import logging
import subprocess

logger = logging.getLogger('biliup')


class NamedLock:
    """
    简单实现的命名锁
    """
    from _thread import LockType
    _lock_dict = {}

    def __new__(cls, name) -> LockType:
        import threading

        # 如果名字不在_lock_dict中
        if name not in cls._lock_dict:
            # 在_lock_dict中创建对应名字的锁对象
            cls._lock_dict[name] = threading.Lock()

        # 返回对应名字的锁对象
        return cls._lock_dict[name]



def silence_event_loop_closed(func):
    from functools import wraps

    @wraps(func)
    def wrapper(self, *args, **kwargs):
        try:
            # 尝试执行传入的函数
            return func(self, *args, **kwargs)
        except RuntimeError as e:
            # 如果捕获到RuntimeError异常
            if str(e) != 'Event loop is closed':
                # 如果异常信息不是"Event loop is closed"，则重新抛出异常
                raise

    return wrapper



def get_file_create_timestamp(file: str) -> float:
    """
    跨平台获取文件创建时间
    如无法获取则返回修改时间
    """
    import os
    import sys
    import platform
    stat_result = os.stat(file)

    # 如果stat_result对象有st_birthtime属性，则直接返回文件的创建时间
    if hasattr(stat_result, "st_birthtime"):
        return stat_result.st_birthtime

    # 如果是Windows系统并且Python版本小于3.12，则返回文件的创建时间（在Windows上，st_ctime表示创建时间）
    if platform.system() == 'Windows' and sys.version_info < (3, 12):
        return stat_result.st_ctime

    # 如果是Linux系统
    if platform.system() == 'Linux':
        try:
            import subprocess
            # 使用stat命令获取文件的创建时间，并解码为浮点数
            time = float(subprocess.check_output(["stat", "-c", "%W", file]).decode('utf8'))
            # 如果时间大于0，则返回文件的创建时间
            if time > 0:
                return time
        except:
            pass

    # 如果以上条件都不满足，则返回文件的最后修改时间
    return stat_result.st_mtime



def processor(processors, data):
    for process in processors:
        if process.get('run'):
            try:
                # 调用 subprocess.check_output 方法执行 process['run'] 指定的命令
                # 并将 data 作为输入传递给命令
                # 将命令的标准输出和标准错误输出合并，并返回字符串类型的结果
                process_output = subprocess.check_output(
                    process['run'], shell=True,
                    input=data,
                    stderr=subprocess.STDOUT, text=True)
                # 打印处理后的输出，去除末尾的换行符
                logger.info(process_output.rstrip())
            except subprocess.CalledProcessError as e:
                # 如果执行命令发生异常，则打印异常输出
                logger.exception(e.output)
                # 继续处理下一个 process
                continue

