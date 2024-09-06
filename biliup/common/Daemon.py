import asyncio
import logging
from signal import SIGTERM
import sys
import os
import time
import atexit

logger = logging.getLogger('biliup')


# python模拟linux的守护进程
class Daemon(object):
    def __init__(self, pidfile, fn, change_currentdirectory=False, stdin='/dev/null', stdout='/dev/null',
                 stderr='/dev/null'):
        # 初始化方法，接收pid文件路径、函数、是否改变当前目录、标准输入、标准输出、标准错误等参数
        # 需要获取调试信息，改为stdin='/dev/stdin', stdout='/dev/stdout', stderr='/dev/stderr'，以root身份运行。
        self.stdin = stdin
        self.stdout = stdout
        self.stderr = stderr
        self.pidfile = pidfile
        self.fn = fn
        self.cd = change_currentdirectory

    def _daemonize(self):
        try:
            pid = os.fork()  # 第一次fork，生成子进程，脱离父进程
            if pid > 0:
                sys.exit(0)  # 退出主进程
        except OSError as e:
            sys.stderr.write('fork #1 failed: %d (%s)\n' % (e.errno, e.strerror))
            sys.exit(1)

        # 如果需要改变当前目录
        if self.cd:
            os.chdir("/")  # 修改工作目录为根目录

        # 设置新的会话连接
        os.setsid()  # 设置新的会话连接

        # 重新设置文件创建权限为0
        os.umask(0)  # 重新设置文件创建权限

        try:
            pid = os.fork()  # 第二次fork，禁止进程打开终端
            if pid > 0:
                sys.exit(0)
        except OSError as e:
            sys.stderr.write('fork #2 failed: %d (%s)\n' % (e.errno, e.strerror))
            sys.exit(1)

        # 重定向文件描述符
        sys.stdout.flush()
        sys.stderr.flush()
        # 打开文件，并获取文件描述符
        # with open(self.stdin, 'r') as si, open(self.stdout, 'a+') as so, open(self.stderr, 'ab+', 0) as se:
        si = open(self.stdin, 'r')
        so = open(self.stdout, 'a+')
        se = open(self.stderr, 'ab+', 0)

        # 将文件描述符重定向到标准输入、输出、错误
        os.dup2(si.fileno(), sys.stdin.fileno())
        os.dup2(so.fileno(), sys.stdout.fileno())
        os.dup2(se.fileno(), sys.stderr.fileno())

        # 注册退出函数，但没有提供退出函数的具体实现
        # 需要在文件pid判断是否存在进程，如果存在则进行相应处理
        # 没有退出函数，根据文件pid判断是否存在进程
        atexit.register(self.delpid)

        # 获取当前进程的pid
        pid = str(os.getpid())

        # 将pid写入pid文件
        with open(self.pidfile, 'w+') as f:
            f.write('%s\n' % pid)

            # file(self.pidfile, 'w+').write('%s\n' % pid)

    def delpid(self):
        # 删除pid文件
        os.remove(self.pidfile)
        # logger.debug('进程结束')

    def start(self):
        # 检查pid文件是否存在以探测是否存在进程
        # logger.debug('准备启动进程')
        try:
            # 打开pid文件
            pf = open(self.pidfile, 'r')
            # 读取pid文件中的pid
            pid = int(pf.read().strip())
            # 关闭pid文件
            pf.close()
        except IOError:
            pid = None

        if pid:
            # 如果pid存在，说明进程已运行，输出提示信息并退出
            message = 'pidfile %s already exist. Daemon already running!\n'
            sys.stderr.write(message % self.pidfile)
            sys.exit(1)

        # 启动监控
        self._daemonize()
        # 运行程序
        self._run()

    def stop(self):
        # 从pid文件中获取pid
        try:
            # 打开pid文件
            pf = open(self.pidfile, 'r')
            # 读取pid文件中的pid
            pid = int(pf.read().strip())
            # 关闭pid文件
            pf.close()
        except IOError:
            pid = None

        if not pid:  # 重启不报错
            # 如果pid不存在，说明进程未运行，输出提示信息并返回
            message = 'pidfile %s does not exist. Daemon not running!\n'
            sys.stderr.write(message % self.pidfile)
            return

        # 杀进程
        try:
            while 1:
                # 向进程组发送SIGTERM信号以结束进程
                os.killpg(os.getpgid(pid), SIGTERM)
                # 等待0.1秒
                time.sleep(0.1)
                # os.system('hadoop-daemon.sh stop datanode')
                # os.system('hadoop-daemon.sh stop tasktracker')
                # os.remove(self.pidfile)
        except OSError as err:
            # 捕获异常
            err = str(err)
            # 如果异常信息是“No such process”，表示进程已不存在
            if err.find('No such process') > 0:
                # 如果pid文件存在，则删除pid文件
                if os.path.exists(self.pidfile):
                    os.remove(self.pidfile)
            else:
                # 输出异常信息
                print(str(err))
                # 退出程序
                sys.exit(1)

    def restart(self):
        # 停止进程
        self.stop()
        # 启动进程
        self.start()

    def _run(self):
        """
        run your fun
        """
        # 运行异步函数
        asyncio.run(self.fn())

