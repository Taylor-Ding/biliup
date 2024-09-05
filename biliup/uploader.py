import inspect
import logging
import time

from biliup.config import config
from .engine.decorators import Plugin

logger = logging.getLogger('biliup')


def upload(data):
    """
    上传入口
    :param platform:
    :param index:
    :param data: 现在需包含内容{url,date} 完整包含内容{url,date,format_title}
    :return:
    """
    try:
        # 从数据字典中获取'name'键对应的值，作为后续操作的索引
        index = data['name']
        # 将配置字典与特定数据源的相关配置合并，为后续操作提供上下文
        context = {**config, **config['streamers'][index]}
        # 根据上下文获取uploader信息，如果不存在则默认为'biliup-rs'
        platform = context.get("uploader") if context.get("uploader") else "biliup-rs"
        # 从Plugin的上传插件字典中获取与platform对应的类
        cls = Plugin.upload_plugins.get(platform)
        # 如果没有找到对应的类，输出错误日志并返回
        if cls is None:
            return logger.error(f"No such uploader: {platform}")
        # 格式化数据的标题和描述，同时更新data字典
        data, context = fmt_title_and_desc(data)
        # 从配置中获取特定配置项，并更新data字典
        data['dolby'] = config.get('dolby', 0)
        data['hires'] = config.get('hires', 0)
        data['no_reprint'] = config.get('no_reprint', 0)
        data['open_elec'] = config.get('open_elec', 0)
        # 检查插件类的签名，以确定需要传递的参数
        sig = inspect.signature(cls)
        kwargs = {}
        for k in sig.parameters:
            v = context.get(k)
            if v:
                kwargs[k] = v
        # 使用获取到的所有参数，初始化插件类并调用其start方法
        return cls(index, data, **kwargs).start()
    except:
        # 捕获并记录所有未捕获的异常
        logger.exception("Uncaught exception:")


def biliup_uploader(filelist, data):
    """
    使用Biliup上传器将文件上传到指定平台。

    参数:
    filelist - 待上传的文件列表。
    data - 包含上传所需信息的字典，如上传者的名称和上传平台的详情。

    返回:
    上传结果，具体格式取决于所使用的上传器和上传过程的结果。
    """
    try:
        # 从data字典中提取上传者的名称
        index = data['name']
        # 创建一个新字典并复制data的内容
        context = {**data}
        # 确定上传平台的名称，如果没有指定则使用默认平台'biliup-rs'
        platform = context.get("uploader") if context.get("uploader") else "biliup-rs"
        # 通过平台名称查找对应的上传器类
        cls = Plugin.upload_plugins.get(platform)
        # 如果没有找到对应的上传器类，记录错误并返回
        if cls is None:
            return logger.error(f"No such uploader: {platform}")
        # 格式化标题和描述（根据具体实现细节）
        data, context = fmt_title_and_desc_m(data)
        # 设置默认值（如果没有提供的话）
        data['dolby'] = data.get('dolby', 0)
        data['hires'] = data.get('hires', 0)
        data['no_reprint'] = data.get('no_reprint', 0)
        data['open_elec'] = data.get('open_elec', 0)
        # 获取上传器类的方法签名
        sig = inspect.signature(cls)
        # 准备上传器类的构造函数参数
        kwargs = {}
        for k in sig.parameters:
            v = context.get(k)
            if v:
                kwargs[k] = v
        # 开始上传过程
        logger.info("start biliup")
        # 调用上传器类的upload方法进行上传
        return cls(index, data, **kwargs).upload(filelist)
    except:
        # 捕获并记录未捕获的异常
        logger.exception("Uncaught exception:")
    else:
        # 上传过程正常结束时记录日志
        logger.info("stop biliup")



def fmt_title_and_desc_m(data):
    """
    格式化标题和描述。

    该函数旨在对给定的数据字典中的标题和描述字段进行格式化处理。
    它使用了自定义的格式化字符串函数，根据上下文中的日期、标题、流媒体信息和URL来生成最终的格式化字符串。

    参数:
    - data: 一个字典，包含录制的相关数据，如'name', 'streamer', 'date', 'title', 'url', 'description'等字段。

    返回:
    - 一个元组，包含两个元素：
        1. 第一个元素是更新了'format_title'字段的原始数据字典。
        2. 第二个元素是上下文字典，其中'description'字段可能已经被格式化。
    """
    # 提取数据字典中的'name'字段作为默认索引
    index = data['name']
    # 创建一个新的上下文字典，包含原始数据字典的所有项
    context = {**data}
    # 'streamer'字段值，如果不存在则默认使用索引
    streamer = data.get('streamer', index)
    # 'date'字段值，如果不存在则默认使用本地时间
    date = data.get("date", time.localtime())
    # 'title'字段值，如果不存在则默认使用索引
    title = data.get('title', index)
    # 获取'url'字段值
    url = data.get('url')

    # 根据上下文中的'title'或默认格式('%Y.%m.%d{index}')以及其它上下文信息生成格式化标题
    data["format_title"] = custom_fmtstr(context.get('title') or f'%Y.%m.%d{index}', date, title, streamer, url)
    # 如果上下文中存在'description'，则对其进行格式化
    if context.get('description'):
        context['description'] = custom_fmtstr(context.get('description'), date, title, streamer, url)

    # 返回格式化后的数据字典和上下文字典
    return data, context


# 将格式化标题和简介拆分出来方便复用
def fmt_title_and_desc(data):
    """
    格式化标题和简介
    :param data: 包含主播名、网址和日期的信息字典
    :return: 格式化后的标题和完整的上下文字典
    """
    # 从输入数据中获取主播索引
    index = data['name']
    # 构建上下文字典，结合配置信息和主播特定信息
    context = {**config, **config['streamers'][index]}
    # 获取主播名称，如果未指定，则使用索引
    streamer = data.get('streamer', index)
    # 获取日期，默认为当前本地时间
    date = data.get("date", time.localtime())
    # 获取标题，默认使用主播索引
    title = data.get('title', index)
    # 获取网址
    url = data.get('url')
    # 格式化标题并添加到数据字典中
    data["format_title"] = custom_fmtstr(context.get('title') or f'%Y.%m.%d{index}', date, title, streamer, url)
    # 如果存在描述，则格式化描述
    if context.get('description'):
        context['description'] = custom_fmtstr(context.get('description'), date, title, streamer, url)
    # 返回格式化后的数据和上下文字典
    return data, context


def custom_fmtstr(string, date, title, streamer, url):
    """
    格式化字符串，用于生成包含时间、标题、主播和URL的定制化字符串。

    该函数首先使用给定的时间参数格式化一个字符串模板，然后解码转义的Unicode字符，
    最后使用标题、主播名和URL填充格式化字符串。

    参数:
    string (str): 字符串模板，可能包含需要替换的占位符。
    date (time.struct_time): 时间结构体，用于格式化时间。
    title (str): 标题，用于替换模板中的占位符。
    streamer (str): 主播名，用于替换模板中的占位符。
    url (str): URL地址，用于替换模板中的占位符。

    返回:
    str: 格式化后的字符串，包含格式化的时间、标题、主播名和URL。
    """
    # 使用time.strftime格式化时间，同时对字符串中的特殊字符进行转义
    # 然后解码转义的Unicode字符，准备进行字符串格式化
    fmt_string = time.strftime(string.encode('unicode-escape').decode(), date)
    # 使用给定的标题、主播名和URL对字符串模板进行格式化
    return fmt_string.format(title=title, streamer=streamer, url=url)

