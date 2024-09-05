# 导入异步io库，用于处理异步任务
import asyncio
# 导入日志库，用于记录程序运行信息
import logging
# 导入线程池执行器，用于创建线程池以并行执行任务
from concurrent.futures import ThreadPoolExecutor

# 导入本地模块
from . import plugins
# 导入配置文件
from biliup.config import config
# 导入插件引擎和相关功能
from biliup.engine import Plugin, invert_dict
# 导入事件管理器和事件类
from biliup.engine.event import EventManager, Event
# 导入定时器和工具类
from .common.timer import Timer
from .common.tools import NamedLock

# 创建日志记录器
logger = logging.getLogger('biliup')

# 定义函数用于创建事件管理器
def create_event_manager():
    # 从配置中获取线程池大小，若未配置则使用默认值
    pool1_size = config.get('pool1_size', 5)
    pool2_size = config.get('pool2_size', 3)
    # 创建两个线程池，分别用于不同类型的异步任务
    pool = {
        'Asynchronous1': ThreadPoolExecutor(pool1_size, thread_name_prefix='Asynchronous1'),
        'Asynchronous2': ThreadPoolExecutor(pool2_size, thread_name_prefix='Asynchronous2'),
        # 可选创建第三个线程池，当前被注释掉
        # 'Asynchronous3': ThreadPoolExecutor(2, thread_name_prefix='Asynchronous3'),
    }
    # 初始化事件管理器，并传入配置和线程池信息
    app = EventManager(config, pool)
    # 在事件管理器上下文中添加用于记录URL上传次数的字典
    app.context['url_upload_count'] = {}
    # 在事件管理器上下文中添加用于记录正在上传的文件名的列表
    app.context['upload_filename'] = []
    # 返回初始化后的事件管理器
    return app

# 创建全局事件管理器实例
event_manager = create_event_manager()
# 获取事件管理器的上下文，方便后续使用
context = event_manager.context

# 定义异步函数用于进行单例检查
async def singleton_check(platform, name, url):
    # 导入处理器中的事件类型
    from biliup.handler import PRE_DOWNLOAD, UPLOAD
    # 若URL未记录在上传次数字典中，则初始化为0
    context['url_upload_count'].setdefault(url, 0)
    # 若该URL的状态为正在下载中，则跳过检测并记录日志
    if context['PluginInfo'].url_status[url] == 1:
        logger.debug(f'{url} 正在下载中，跳过检测')
        return

    # 发送上传事件
    event_manager.send_event(Event(UPLOAD, ({'name': name, 'url': url},)))
    # 调用平台的acheck_stream方法进行流检查，并等待结果
    if await platform(name, url).acheck_stream(True):
        # 使用命名锁确保上传文件列表检索的原子性
        with NamedLock(f'upload_file_list_{name}'):
            # 发送预下载事件
            event_manager.send_event(Event(PRE_DOWNLOAD, args=(name, url,)))

# 定义异步函数用于处理事件列表中的任务
async def shot(event):
    index = 0
    # 无限循环处理任务列表
    while True:
        # 若任务列表为空，则记录日志并退出循环
        if not len(event.url_list):
            logger.info(f"{event}没有任务，退出")
            return
        # 若索引超出任务列表长度，则重置为0
        if index >= len(event.url_list):
            index = 0
            continue
        # 获取当前任务URL
        cur = event.url_list[index]
        try:
            # 调用单例检查函数，并传入相关参数
            await singleton_check(event, context['PluginInfo'].inverted_index[cur], cur)
            # 处理下一个任务
            index += 1
            # 若当前URL正在下载且还有未处理的任务，则跳过本次等待以加快下一个检测
            skip = context['PluginInfo'].url_status[cur] == 1 and index < len(event.url_list)
            if skip:
                continue
        except Exception:
            # 若处理过程中出现异常，则记录异常日志
            logger.exception('shot')
        # 每次处理完一个任务后，等待一段时间再进行下一个任务的处理，等待时间从配置中获取，默认为30秒
        await asyncio.sleep(config.get('event_loop_interval', 30))

# 使用装饰器将PluginInfo类注册为事件管理器的一个服务，这样事件管理器可以自动管理该类的实例化和生命周期
@event_manager.server()
class PluginInfo:
    # 构造函数，传入streamers字典，包含各平台的信息和配置
    def __init__(self, streamers):
        # 从streamers字典中提取URL信息，并构建反向索引字典，方便后续通过URL查找平台信息
        streamer_url = {k: v['url'] for k, v in streamers.items()}
        self.inverted_index = invert_dict(streamer_url)
        # 获取反向索引字典的所有键，即所有URL列表
        urls = list(self.inverted_index.keys())
        # 根据URL列表初始化检查器，并按照配置进行排序
        self.checker = Plugin(plugins).sorted_checker(urls)
        # 初始化URL状态字典，所有URL的初始状态为0（未下载）
        self.url_status = dict.fromkeys(self.inverted_index, 0)
        # 初始化协程字典，用于存储每个检查器对应的协程任务
        self.coroutines = dict.fromkeys(self.checker)
        # 调用init_tasks方法初始化任务
        self.init_tasks()

    # 添加新的URL到检查器中进行管理
    def add(self, name, url):
        # 根据URL获取对应的检查器类
        temp = Plugin(plugins).inspect_checker(url)
        key = temp.__name__
        # 若检查器已存在，则将URL添加到该检查器的任务列表中
        if key in self.checker:
            self.checker[key].url_list.append(url)
        else:
            # 若检查器不存在，则创建一个新的检查器实例，并将URL添加到其任务列表中
            temp.url_list = [url]
            self.checker[key] = temp
            # 判断检查器是否支持批量检测，若支持则调用batch_check_task方法进行处理
            from .engine.download import BatchCheck
            if issubclass(temp, BatchCheck):
                self.batch_check_task(temp)
            else:
                # 若不支持批量检测，则创建一个新的协程任务进行处理，并将任务添加到协程字典中
                self.coroutines[key] = asyncio.create_task(shot(temp))
        # 更新反向索引字典和URL状态字典
        self.inverted_index[url] = name
        self.url_status[url] = 0

    # 从检查器中删除指定的URL
    def delete(self, url):
        # 若URL不存在于反向索引字典中，则直接返回
        if not url in self.inverted_index:
            return
        # 从反向索引字典中删除URL对应的条目
        del self.inverted_index[url]
        exec_del = False
        # 遍历检查器字典，查找并删除包含指定URL的条目
        for key, value in self.checker.items():
            if url in value.url_list:
                if len(value.url_list) == 1:
                    exec_del = key
                else:
                    value.url_list.remove(url)
        # 若某个检查器的任务列表已空，则取消对应的协程任务，并从协程字典和检查器字典中删除该条目
        if exec_del:
            del self.checker[exec_del]
            self.coroutines[exec_del].cancel()
            del self.coroutines[exec_del]

    # 初始化任务，根据检查器类型创建对应的协程任务进行处理
    def init_tasks(self):
        from .engine.download import BatchCheck

        for key, plugin in self.checker.items():
            if issubclass(plugin, BatchCheck):
                # 若支持批量检测，则调用batch_check_task方法进行处理，并继续下一次循环
                self.batch_check_task(plugin)
                continue
            # 若不支持批量检测，则创建一个新的协程任务进行处理，并将任务添加到协程字典中
            self.coroutines[key] = asyncio.create_task(shot(plugin))

    def batch_check_task(self, plugin):
        """
        批量检测任务函数。

        该函数负责创建并启动一个定时任务，该任务将异步检测给定插件的URL列表。
        每当检测到一个新的URL时，它会通知事件管理器以触发预下载事件。

        参数:
        plugin: 插件实例，包含要检测的URL列表以及支持批量检测的方法。

        返回:
        无返回值，但启动了一个异步任务来执行批量检测逻辑。
        """
        # 导入预下载事件类型
        from biliup.handler import PRE_DOWNLOAD

        # 定义一个内部的异步定时器函数来处理批量检测逻辑
        async def check_timer():
            # 初始化任务名称
            name = None
            # 如果支持批量检测
            try:
                # 遍历插件的URL列表，进行异步批量检测
                async for turl in plugin.abatch_check(plugin.url_list):
                    # 初始化URL上传计数
                    context['url_upload_count'].setdefault(turl, 0)
                    # 查找配置中对应的流媒体信息
                    for k, v in config['streamers'].items():
                        if v.get("url", "") == turl:
                            name = k
                    # 发送预下载事件
                    event_manager.send_event(Event(PRE_DOWNLOAD, args=(name, turl,)))
            except Exception:
                # 异常处理，记录日志
                logger.exception('batch_check_task')

        # 创建定时器，每30秒执行一次check_timer任务
        timer = Timer(func=check_timer, interval=30)
        # 在协程任务字典中为当前插件注册定时任务
        self.coroutines[plugin.__name__] = asyncio.create_task(timer.astart())
