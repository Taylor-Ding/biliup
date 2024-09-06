import asyncio
import threading


class Timer(threading.Thread):
    def __init__(self, func=None, args=(), kwargs=None, interval=15, daemon=True):
        # 调用父类构造函数
        threading.Thread.__init__(self, daemon=daemon)
        # 如果没有传入kwargs参数，则默认为空字典
        if kwargs is None:
            kwargs = {}
        # 将传入的参数保存到实例变量中
        self._args = args
        self._kwargs = kwargs
        # 创建一个线程事件对象
        self._flag = threading.Event()
        # 将传入的函数保存到实例变量中
        self._func = func
        # 设置时间间隔
        self.interval = interval
        # 保存异步任务对象
        self.task = None
        # 标记是否为异步任务
        self.asynchronous = False

    async def astart(self):
        # 标记为异步任务
        self.asynchronous = True
        # 创建一个异步任务
        self.task = asyncio.create_task(self.arun())
        # 等待异步任务完成
        await self.task

    async def arun(self):
        while True:
            # 执行异步定时器
            await self.atimer()
            # 等待一定时间
            await asyncio.sleep(self.interval)

    async def atimer(self):
        # 调用传入的函数，并传入保存的参数
        await self._func(*self._args, **self._kwargs)

    def timer(self):
        # 调用传入的函数，并传入保存的参数
        self._func(*self._args, **self._kwargs)

    def run(self):
        # 当线程事件未设置时执行循环
        while not self._flag.is_set():
            # 执行定时器
            self.timer()
            # 等待一定时间，或者直到线程事件被设置
            self._flag.wait(self.interval)

    def stop(self):
        # 如果不是异步任务，则设置线程事件
        if not self.asynchronous:
            return self._flag.set()
        # 取消异步任务
        self.task.cancel()

