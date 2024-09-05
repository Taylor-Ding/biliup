import logging
import re

from .engine.decorators import Plugin
from .plugins import general
# 初始化日志记录器，用于记录biliup相关的日志信息
logger = logging.getLogger('biliup')

def download(fname, url, **kwargs):
    """
    根据URL下载资源。

    该函数会遍历所有下载插件，寻找可以处理给定URL的合适插件。
    如果找到匹配的插件，会使用该插件初始化下载过程，并应用任何额外的参数。
    如果没有找到匹配的插件，会使用通用插件进行处理，并记录警告日志。

    参数:
    - fname: 资源名称，通常用于命名下载的文件。
    - url: 资源的URL地址。
    - **kwargs: 额外的关键字参数，用于配置下载过程。

    返回:
    - 插件处理的结果。
    """
    pg = None
    # 遍历所有下载插件，寻找与URL模式匹配的插件
    for plugin in Plugin.download_plugins:
        if re.match(plugin.VALID_URL_BASE, url):
            pg = plugin(fname, url)
            # 应用额外的参数到插件实例
            for k in pg.__dict__:
                if kwargs.get(k):
                    pg.__dict__[k] = kwargs.get(k)
            break
    # 如果没有找到匹配的插件，使用通用插件处理
    if not pg:
        pg = general.__plugin__(fname, url)
        logger.warning(f'Not found plugin for {fname} -> {url} This may cause problems')
    return pg.start()

def biliup_download(name, url, kwargs: dict):
    """
    biliup的下载函数，用于处理特定格式的资源下载。

    该函数会移除字典中的URL参数，因为该参数已经被函数签名中的'url'参数所使用。
    如果字典中存在'format'键，会将其值作为下载文件的后缀名，并将该信息更新到参数字典中。
    随后调用通用的download函数开始下载过程。

    参数:
    - name: 资源的名称。
    - url: 资源的URL地址。
    - kwargs: 包含额外下载参数的字典。

    返回:
    - 下载结果，由download函数返回。
    """
    kwargs.pop('url')  # 移除字典中的URL参数，避免重复传递
    suffix = kwargs.get('format')
    if suffix:
        kwargs['suffix'] = suffix  # 如果存在format参数，将其作为文件后缀名
    return download(name, url, **kwargs)
