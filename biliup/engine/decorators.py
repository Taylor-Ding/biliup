import functools
import importlib
import pkgutil
import re


def suit_url(pattern, urls):
    # 定义一个空列表用于存储匹配的URL
    sorted_url = []
    # 从urls列表的最后一个元素开始往前遍历
    for i in range(len(urls) - 1, -1, -1):
        # 如果当前URL匹配给定的模式
        if re.match(pattern, urls[i]):
            # 将匹配的URL添加到sorted_url列表中
            sorted_url.append(urls[i])
            # 从urls列表中移除已匹配的URL
            urls.remove(urls[i])
    # 返回匹配并排序后的URL列表
    return sorted_url



class Plugin:
    # 下载插件列表
    download_plugins = []
    # 上传插件字典
    upload_plugins = {}

    def __init__(self, pkg):
        # 加载插件
        self.load_plugins(pkg)

    @staticmethod
    def download(regexp):
        def decorator(cls):
            # 设置插件的URL基础正则表达式
            cls.VALID_URL_BASE = regexp
            # 将插件类添加到下载插件列表中
            Plugin.download_plugins.append(cls)
            return cls
        return decorator

    @staticmethod
    def upload(platform):
        def decorator(cls):
            @functools.wraps(cls)
            def wrapper(*args, **kw):
                # 打印参数列表
                print(f"args {args}")
                # 打印关键字参数字典
                print(f"kw {kw}")
                return cls(*args, **kw)
            # 将插件包装函数添加到上传插件字典中，以平台为键
            Plugin.upload_plugins[platform] = wrapper
            return wrapper
        return decorator


    @classmethod
    def sorted_checker(cls, urls):
        # 如果传入的urls为空，则直接返回一个空字典
        if not urls:
            return {}
        # 导入general插件模块
        from ..plugins import general
        # 复制urls列表
        curls = urls.copy()
        # 初始化checker_plugins字典
        checker_plugins = {}
        # 遍历下载插件列表
        for plugin in cls.download_plugins:
            # 调用suit_url函数，根据插件的URL基础正则表达式筛选出匹配的URL列表
            url_list = suit_url(plugin.VALID_URL_BASE, curls)
            # 如果筛选出的URL列表为空，则跳过当前循环
            if not url_list:
                continue
            else:
                # 将筛选出的URL列表赋值给插件的url_list属性
                plugin.url_list = url_list
                # 将插件及其名称添加到checker_plugins字典中
                checker_plugins[plugin.__name__] = plugin
            # 如果筛选后的urls列表为空，则提前返回checker_plugins字典
            if not curls:
                return checker_plugins
        # 将剩余的urls列表赋值给general插件的url_list属性
        general.__plugin__.url_list = curls
        # 将general插件及其名称添加到checker_plugins字典中
        checker_plugins[general.__plugin__.__name__] = general.__plugin__
        # 返回checker_plugins字典
        return checker_plugins


    @classmethod
    def inspect_checker(cls, url):
        # 导入general插件模块
        from ..plugins import general
        # 遍历下载插件列表
        for plugin in cls.download_plugins:
            # 如果当前插件的URL基础正则表达式与传入的url不匹配
            if not re.match(plugin.VALID_URL_BASE, url):
                # 继续下一次循环
                continue
            else:
                # 返回匹配的插件
                return plugin
        # 如果没有找到匹配的插件，则返回general插件
        return general.__plugin__

    def load_plugins(self, pkg):
        """Attempt to load plugins from the path specified.
        engine.plugins.__path__[0]: full path to a directory where to look for plugins
        """

        plugins = []

        # 遍历指定路径下的模块
        for loader, name, ispkg in pkgutil.iter_modules([pkg.__path__[0]]):
            # 设置完整的插件模块名
            # set the full plugin module name
            module_name = f"{pkg.__name__}.{name}"
            # 导入插件模块
            module = importlib.import_module(module_name)
            if ispkg:
                # 如果模块是包，则递归加载该包下的插件
                self.load_plugins(module)
                continue
            if module in plugins:
                # 如果插件已经加载过，则跳过
                continue
            # 将插件添加到插件列表中
            plugins.append(module)
        return plugins

