import asyncio
import logging
import subprocess
import sys
import os
from .timer import Timer
# 获取名为'biliup'的日志记录器
logger = logging.getLogger('biliup')

# 声明全局变量global_reloader
global global_reloader


def has_extension(fname_list, *extension):
    # 遍历文件名列表
    for fname in fname_list:
        # 使用map函数将文件名与扩展名列表进行匹配，判断文件名是否以扩展名结尾
        result = list(map(fname.endswith, extension))
        # 如果存在匹配结果（即文件名以某个扩展名结尾）
        if True in result:
            # 返回True
            return True
    return False



class AutoReload(Timer):
    def __init__(self, *watched, interval=10):
        super().__init__(interval)
        # 存储被监控的文件或目录
        self.watched = watched
        # 存储文件的最后修改时间
        self.mtimes = {}
        # 标记是否触发过文件变化
        self.triggered = False

    @staticmethod
    def _iter_module_files():
        """Iterator to module's source filename of sys.modules (built-in
        excluded).
        """
        # 遍历sys.modules中的所有模块
        for module in list(sys.modules.values()):
            # 获取模块的源文件名
            filename = getattr(module, '__file__', None)
            if filename:
                # 如果文件名是.pyo或.pyc结尾，则去掉最后一个字符
                if filename[-4:] in ('.pyo', '.pyc'):
                    filename = filename[:-1]
                # 返回源文件名
                yield filename

    def _is_any_file_changed(self):
        """Return 1 if there is any source file of sys.modules changed,
        otherwise 0. mtimes is dict to store the last modify time for
        comparing."""
        # 遍历所有模块的源文件名
        for filename in self._iter_module_files():
            try:
                # 获取文件的最后修改时间
                mtime = os.stat(filename).st_mtime
            except IOError:
                # 如果文件不存在或无法访问，则跳过
                continue
            # 获取文件中存储的最后修改时间
            old_time = self.mtimes.get(filename, None)
            if old_time is None:
                # 如果文件之前没有记录过最后修改时间，则记录当前时间
                self.mtimes[filename] = mtime
            elif mtime > old_time:
                # 如果文件的最后修改时间发生了变化
                logger.info('模块已更新')
                # 标记触发过文件变化
                return True
        # 如果所有文件的最后修改时间都没有发生变化
        return False

    @staticmethod
    def _work_free():
        # 获取当前目录下的所有文件名
        fname_list = os.listdir('.')
        # 如果存在指定扩展名的文件，则返回False
        if has_extension(fname_list, '.mp4', '.flv', '.3gp', '.webm', '.mkv', '.ts', '.part'):
            return False
        # 标记进程空闲
        logger.info('进程空闲')
        return True

    async def atimer(self):
        """Check file state ervry interval. If any change is detected, exit this
        process with a special code, so that deamon will to restart a new process.
        """
        # 如果文件没有变化且之前没有触发过文件变化
        if not self._is_any_file_changed() and not self.triggered:
            # 则直接返回，不进行后续操作
            return
        while True:
            # 等待指定时间间隔
            await asyncio.sleep(self.interval)
            # 如果进程空闲
            if self._work_free():
                # 遍历被监控的文件或目录
                for watched in self.watched:
                    if callable(watched):
                        # 如果被监控的是一个函数
                        if asyncio.iscoroutinefunction(watched):
                            # 如果函数是一个协程函数，则等待其执行完毕
                            await watched()
                        else:
                            # 如果函数不是协程函数，则直接执行
                            watched()
                    else:
                        # 如果被监控的不是一个函数，则假设它是一个定时器对象，并停止它
                        watched.stop()
                # 停止当前定时器
                self.stop()
                # 标记触发过文件变化
                # parent_path = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))  # 获得所在的目录的父级目
                # path = os.path.join(parent_path, '__main__.py')
                # if sys.platform == 'win32':
                #     args = ["python", path]
                # else:
                #     args = [path, 'start']
                logger.info('重启')
                # 如果不是Docker环境，则启动一个新的进程
                if not is_docker():
                    subprocess.Popen(sys.argv)
                # 退出当前函数
                return



def is_docker():
    # 定义文件路径
    path = '/proc/self/cgroup'
    return (
            # 判断是否存在文件 '/.dockerenv'
            os.path.exists('/.dockerenv') or
            # 判断文件 'path' 是否存在，并且其中任意一行包含 'docker'
            os.path.isfile(path) and any('docker' in line for line in open(path))
    )
