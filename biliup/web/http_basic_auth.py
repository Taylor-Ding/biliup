"""
HTTP Basic Auth python lib from https://github.com/bugov/http-basic-auth
"""

import base64
from typing import Tuple

__version__ = '1.2.0'


class BasicAuthException(Exception):
    """General exception for all http-basic-auth problems
    """

def parse_token(token: str, coding='utf-8') -> Tuple[str, str]:
    """从Basic Auth token中获取登录名和密码的元组。
    """
    try:
        # 将token字符串编码为字节类型
        b_token = bytes(token, encoding=coding)
    except UnicodeEncodeError as e:
        raise BasicAuthException from e
    except TypeError as e:
        raise BasicAuthException from e

    try:
        # 对字节类型的token进行base64解码
        auth_pair = base64.b64decode(b_token, validate=True)
    except base64.binascii.Error as e:
        raise BasicAuthException from e

    try:
        # 使用冒号分割解码后的auth_pair，得到登录名和密码
        (login, password) = auth_pair.split(b':', maxsplit=1)
    except ValueError as e:
        raise BasicAuthException from e

    try:
        # 将登录名和密码从字节类型解码为字符串类型，并返回
        return str(login, encoding=coding), str(password, encoding=coding)
    except UnicodeDecodeError as e:
        raise BasicAuthException from e



def generate_token(login: str, password: str, coding='utf-8') -> str:
    """Generate Basic Auth token from login and password
    """
    try:
        # 将登录名转换为字节类型
        b_login = bytes(login, encoding=coding)
        # 将密码转换为字节类型
        b_password = bytes(password, encoding=coding)
    except UnicodeEncodeError as e:
        # 如果发生Unicode编码错误，则抛出BasicAuthException异常
        raise BasicAuthException from e
    except TypeError as e:
        # 如果发生类型错误，则抛出BasicAuthException异常
        raise BasicAuthException from e

    # 如果登录名字节中包含冒号，则抛出BasicAuthException异常
    if b':' in b_login:
        raise BasicAuthException

    # 将登录名和密码拼接为字符串格式，并进行base64编码
    b_token = base64.b64encode(b'%b:%b' % (b_login, b_password))

    # 将编码后的token转换为字符串类型，并返回
    return str(b_token, encoding=coding)



def parse_header(header_value: str, coding='utf-8') -> Tuple[str, str]:
    """从Basic Auth头部值中获取登录名和密码的元组。
    """
    # 如果头部值为空，则抛出异常
    if header_value is None:
        raise BasicAuthException

    try:
        # 去除头部值两侧的空格，并按最大分割次数为1进行分割
        basic_prefix, token = header_value.strip().split(maxsplit=1)
    except AttributeError as e:
        raise BasicAuthException from e
    except ValueError as e:
        raise BasicAuthException from e

    # 如果前缀不是'basic'，则抛出异常
    if basic_prefix.lower() != 'basic':
        raise BasicAuthException

    # 解析token，返回登录名和密码的元组
    return parse_token(token, coding=coding)


def generate_header(login: str, password: str, coding='utf-8') -> str:
    """从登录名和密码生成Basic Auth头部值
    """
    # 生成token，并将其添加到'Basic '前缀后返回
    return 'Basic %s' % generate_token(login, password, coding=coding)

