# encoding: UTF-8
# 系统模块
import functools
import inspect
import logging
from collections.abc import Generator
from dataclasses import dataclass, field
from queue import Queue
from threading import *

logger = logging.getLogger('biliup')


class EventManager(Thread):
    def __init__(self, context=None, pool=None):
        """初始化事件管理器"""
        super().__init__(name='Synchronous', daemon=True)
        if pool is None:
            pool = {}
        if context is None:
            context = {}
        self.context = context
        # 事件对象列表
        self.__eventQueue = Queue()
        # 事件管理器开关
        self.__active = True
        # 事件处理线程池
        self._pool = pool
        # 阻塞函数列表
        self.__block = []

        # 这里的__handlers是一个字典，用来保存对应的事件的响应函数
        # 其中每个键对应的值是一个列表，列表中保存了对该事件监听的响应函数，一对多
        self.__handlers = {}

        self.__method = {}

    def run(self):
        # 当线程处于活动状态时执行循环
        while self.__active:
            # 从事件队列中获取事件
            event = self.__eventQueue.get()
            # 如果事件不为空
            if event is not None:
                # 调用事件处理函数处理事件
                self.__event_process(event)


    def __event_process(self, event):
        """处理事件"""
        # 检查是否存在对该事件进行监听的处理函数
        if not self.__active or event.type_ not in self.__handlers:
            return

        # 若存在，则按顺序将事件传递给处理函数执行
        for handler in self.__handlers[event.type_]:
            # 如果处理函数被阻塞，则将其提交到对应的线程池进行异步执行
            if handler.__qualname__ in self.__block:
                self._pool.get(handler.pool).submit(handler, event)
            # 如果处理函数未被阻塞，则直接执行
            else:
                handler(event)


    def stop(self):
        """停止"""
        # 将事件管理器设为停止
        self.__active = False
        # 向事件队列中放入一个None对象，表示停止信号
        self.__eventQueue.put(None)
        # 遍历线程池字典中的每个线程池
        for pool in self._pool.values():
            # 关闭线程池
            pool.shutdown()

    def add_event_listener(self, type_, handler):
        """绑定事件和监听器处理函数"""
        # 尝试获取该事件类型对应的处理函数列表，若无则创建
        try:
            handlerlist = self.__handlers[type_]
        except KeyError:  # 修正错误类型，应为KeyError
            handlerlist = []

        # 将处理函数列表重新赋值给事件类型对应的处理函数列表
        self.__handlers[type_] = handlerlist

        # 若要注册的处理器不在该事件的处理器列表中，则注册该事件
        if handler not in handlerlist:
            # 使用functools.wraps装饰器保留被包装函数的信息
            @functools.wraps(handler)
            def try_handler(event):
                try:
                    # 调用处理器处理事件
                    handler(event)
                except Exception as e:  # 捕获所有异常，并输出错误信息
                    logger.exception('try_handler error: %s' % str(e))

            # 将新的处理器添加到处理器列表中
            handlerlist.append(try_handler)


    def remove_event_listener(self, type_, handler):
        """移除监听器的处理函数"""
        try:
            handler_list = self.__handlers[type_]
            for method in handler_list:
                # 如果该函数存在于列表中，则移除
                if handler.__qualname__ == method.__qualname__:
                    handler_list.remove(method)

                # 如果函数列表为空，则从引擎中移除该事件类型
            if not handler_list:
                # 如果处理函数列表为空，则从引擎中删除该事件类型对应的键
                del self.__handlers[type_]

        except KeyError:
            pass


    def send_event(self, event):
        """发送事件，向事件队列中存入事件"""
        self.__eventQueue.put(event)

    def register(self, type_, block=False):
        # 获取当前函数的外层调用栈中的函数名
        classname = inspect.getouterframes(inspect.currentframe())[1][3]

        # 定义一个回调函数，用于处理发送事件的结果
        def callback(result):
            # 如果结果不为真，则不执行任何操作
            if not result:
                pass
            # 如果结果是元组或生成器类型
            elif isinstance(result, (tuple, Generator)):
                # 遍历事件列表，逐个发送事件
                for event in result:
                    self.send_event(event)
            # 如果结果是其他类型
            else:
                # 直接发送事件
                self.send_event(result)

        # 定义一个函数，用于将函数添加到阻塞列表中
        def appendblock(fc, blk):
            if blk:
                # 如果需要阻塞，则将函数名添加到阻塞列表中
                self.__block.append(fc.__qualname__)

        # 判断当前调用者是否是模块级别
        if classname == '<module>':
            # 定义一个装饰器函数
            def decorator(func):
                # 将函数添加到阻塞列表中
                appendblock(func, block)

                # 使用functools.wraps装饰器保留被装饰函数的元信息
                @functools.wraps(func)
                def wrapper(event):
                    # 调用被装饰函数，并将结果传递给回调函数
                    _event = func(*event.args)
                    callback(_event)
                    return _event

                # 设置装饰器函数的pool属性
                wrapper.pool = block
                # 注册事件监听器
                self.add_event_listener(type_, wrapper)
                # 返回装饰器函数
                return wrapper
        else:
            # 定义一个装饰器函数
            def decorator(func):
                # 将函数添加到阻塞列表中
                appendblock(func, block)

                # 设置当前类型的事件处理方法列表
                self.__method.setdefault(type_, [])
                # 将函数名添加到当前类型的事件处理方法列表中
                self.__method[type_].append(func.__name__)

                # 使用functools.wraps装饰器保留被装饰函数的元信息
                @functools.wraps(func)
                def wrapper(this, event):
                    # 调用被装饰函数，并将结果传递给回调函数
                    _event = func(this, *event.args)
                    callback(_event)
                    return _event

                # 设置装饰器函数的pool属性
                wrapper.pool = block
                # 返回装饰器函数
                return wrapper
        # 返回装饰器
        return decorator


    def server(self):
        # 定义一个装饰器函数
        def decorator(cls):
            # 获取类方法的签名
            sig = inspect.signature(cls)
            # 创建一个空字典用于存储关键字参数
            kwargs = {}
            # 遍历签名中的参数
            for k in sig.parameters:
                # 将参数名作为键，从self.context中获取对应的值作为值，存入kwargs字典中
                kwargs[k] = self.context[k]
            # 使用kwargs字典中的参数创建类的实例
            instance = cls(**kwargs)
            # 将类的实例存入self.context字典中，以类的名字作为键
            self.context[cls.__name__] = instance
            # 遍历self.__method字典中的事件类型
            for type_ in self.__method:
                # 遍历当前事件类型对应的处理方法列表
                for handler in self.__method[type_]:
                    # 注册事件监听器，将处理方法与当前实例绑定后注册到指定的事件类型上
                    self.add_event_listener(type_, getattr(instance, handler))
            # 清空self.__method字典
            self.__method.clear()
            # 返回装饰器函数装饰后的类
            return cls

        # 返回装饰器函数
        return decorator



@dataclass
class Event:
    """事件对象"""
    # 事件类型
    type_: str  # 事件类型
    # 事件的参数，默认为空元组
    args: tuple = ()
    # 字典用于保存具体的事件数据，使用默认工厂函数创建空字典
    # type: ignore # 忽略类型检查警告
    dict: dict = field(default_factory=dict)  # type: ignore # 字典用于保存具体的事件数据
