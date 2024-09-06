"""
https://github.com/bugov/aiohttp-basicauth-middleware
"""

import inspect
import logging
from typing import (
    Callable,
    Iterable,
    Type,
    Coroutine,
    Tuple
)
from aiohttp import web
from .http_basic_auth import parse_header, BasicAuthException


log = logging.getLogger(__name__)


class BaseStrategy:
    def __init__(self, request: web.Request, storage: dict, handler: Callable, header: str):
        # 初始化方法，接收四个参数：请求对象、存储字典、处理函数和头部信息
        self.request = request
        # 将请求对象赋值给实例变量request
        self.storage = storage
        # 将存储字典赋值给实例变量storage
        self.handler = handler
        # 将处理函数赋值给实例变量handler
        self.header = header
        # 将头部信息赋值给实例变量header

        log.debug('Init strategy %r', (self.request, self.storage, self.handler))
        # 记录日志，打印初始化策略的相关信息

    def get_credentials(self) -> Tuple[str, str]:
        try:
            # 尝试解析头部信息，返回登录名和密码的元组
            return parse_header(self.header)
        except BasicAuthException:
            # 如果解析头部信息发生异常，记录日志并调用错误处理函数
            log.info('Invalid basic auth header: %r', self.header)
            self.on_error()

    async def password_test(self) -> bool:
        # 异步方法，测试密码是否正确
        login, password = self.get_credentials()
        # 调用get_credentials方法获取登录名和密码
        server_password = self.storage.get(login)
        # 从存储字典中获取对应登录名的密码

        if server_password != password:
            # 如果服务器密码与输入密码不一致，返回False
            return False

        return True
        # 如果密码一致，返回True

    async def check(self) -> web.Response:
        # 异步方法，检查验证是否通过
        if await self.password_test():
            # 如果密码测试通过，调用处理函数并返回结果
            return await self.handler(self.request)

        self.on_error()
        # 如果密码测试未通过，调用错误处理函数

    def on_error(self):
        # 错误处理函数，抛出HTTP未授权异常，并设置响应头信息
        raise web.HTTPUnauthorized(headers={'WWW-Authenticate': 'Basic'})

def check_access(
    auth_dict: dict,
    header_value: str,
    strategy: Callable = lambda x: x
) -> bool:
    # 调试日志：检查访问权限: %r
    # log.debug('Check access: %r', header_value)
    print('Check access: %r', header_value)

    try:
        # 解析头部值获取登录名和密码
        login, password = parse_header(header_value)
    except BasicAuthException:
        return False

    # 获取存储的哈希密码
    hashed_password = auth_dict.get(login)
    # 对请求中的密码进行哈希处理
    hashed_request_password = strategy(password)

    # 如果存储的哈希密码与请求中的哈希密码不匹配，则返回False
    if hashed_password != hashed_request_password:
        return False

    # 调试日志：%r 登录成功
    # log.debug('%r log in successed', "biliup")
    return True



def basic_auth_middleware(
    urls: Iterable,
    auth_dict: dict,
    strategy: Type[BaseStrategy] = lambda x: x
) -> Coroutine:
    async def factory(app, handler) -> Coroutine:
        async def middleware(request) -> web.Response:
            for url in urls:
                # 判断请求的URL是否以指定URL开头
                if not request.path.startswith(url):
                    continue

                # 如果strategy是BaseStrategy的子类且为类对象
                if inspect.isclass(strategy) and issubclass(strategy, BaseStrategy):
                    # 打印日志，输出使用的Strategy类名
                    log.debug("Use Strategy: %r", strategy.__name__)
                    # 实例化strategy，传入request、auth_dict、handler和Authorization头部信息
                    strategy_obj = strategy(
                        request,
                        auth_dict,
                        handler,
                        request.headers.get('Authorization', '')
                    )
                    # 调用strategy的check方法进行权限验证
                    return await strategy_obj.check()

                # 如果权限验证不通过
                if not check_access(auth_dict, request.headers.get('Authorization', ''), strategy):
                    # 抛出HTTPUnauthorized异常，并设置WWW-Authenticate头为'Basic'
                    raise web.HTTPUnauthorized(headers={'WWW-Authenticate': 'Basic'})

            # 如果请求的URL与所有指定URL都不匹配，则直接调用handler处理请求
            return await handler(request)
        return middleware
    return factory

