#!/usr/bin/python3
# coding:utf8
import argparse
import asyncio
import logging.config
import platform
import shutil

import biliup.common.reload
from biliup.config import config
from biliup import __version__, LOG_CONF
from biliup.common.Daemon import Daemon
from biliup.common.reload import AutoReload
from biliup.common.log import DebugLevelFilter


def arg_parser():
    # 创建一个守护进程对象
    daemon = Daemon('watch_process.pid', lambda: main(args))
    # 创建argparse对象，用于解析命令行参数
    parser = argparse.ArgumentParser(description='Stream download and upload, not only for bilibili.')
    # 添加版本参数
    parser.add_argument('--version', action='version', version=f"v{__version__}")
    # 添加web api主机地址参数
    parser.add_argument('-H', help='web api host [default: 0.0.0.0]', dest='host')
    # 添加web api端口参数
    parser.add_argument('-P', help='web api port [default: 19159]', default=19159, dest='port')
    # 添加禁用web api参数
    parser.add_argument('--no-http', action='store_true', help='disable web api')
    # 添加自定义ui的web静态文件目录参数
    parser.add_argument('--static-dir', help='web static files directory for custom ui')
    # 添加web ui密码参数
    parser.add_argument('--password', help='web ui password ,default username is biliup', dest='password')
    # 添加增加输出详细程度的参数
    parser.add_argument('-v', '--verbose', action="store_const", const=logging.DEBUG, help="Increase output verbosity")
    # 添加配置文件位置参数
    parser.add_argument('--config', type=argparse.FileType(mode='rb'),
                        help='Location of the configuration file (default "./config.yaml")')
    # 添加禁用web访问日志参数
    parser.add_argument('--no-access-log', action='store_true', help='disable web access log')
    # 添加子命令解析器
    subparsers = parser.add_subparsers(help='Windows does not support this sub-command.')

    # 创建"start"命令的解析器
    # create the parser for the "start" command
    parser_start = subparsers.add_parser('start', help='Run as a daemon process.')
    # 设置"start"命令的默认处理函数
    parser_start.set_defaults(func=daemon.start)

    # 创建"stop"命令的解析器
    parser_stop = subparsers.add_parser('stop', help='Stop daemon according to "watch_process.pid".')
    # 设置"stop"命令的默认处理函数
    parser_stop.set_defaults(func=daemon.stop)

    # 创建"restart"命令的解析器
    parser_restart = subparsers.add_parser('restart')
    # 设置"restart"命令的默认处理函数
    parser_restart.set_defaults(func=daemon.restart)

    # 设置默认处理函数
    parser.set_defaults(func=lambda: asyncio.run(main(args)))
    # 解析命令行参数
    args = parser.parse_args()

    # 将解析得到的参数保存到全局变量中
    biliup.common.reload.program_args = args.__dict__

    # 判断是否为"stop"命令
    is_stop = args.func == daemon.stop

    # 如果不是"stop"命令，执行以下代码块
    if not is_stop:
        # 导入数据库相关模块
        from biliup.database.db import SessionLocal, init
        # 创建数据库会话
        with SessionLocal() as db:
            # 初始化变量
            from_config = False
            try:
                # 加载配置文件
                config.load(args.config)
                # 设置from_config为True
                from_config = True
            except FileNotFoundError:
                # 如果没有找到配置文件，则打印提示信息
                print(f'新版本不依赖配置文件，请访问 WebUI 修改配置')

            # 调用init函数进行初始化，并返回结果
            if init(args.no_http, from_config):
                # 如果从配置文件中加载了配置，则将配置保存到数据库中
                if from_config:
                    config.save_to_db(db)
            # 从数据库中加载配置
            config.load_from_db(db)

        # 从配置中获取日志配置
        LOG_CONF.update(config.get('logging', {}))

        # 如果设置了详细输出参数，则更新日志配置中的级别
        if args.verbose:
            # 如果设置了详细输出参数，则更新日志配置中的biliup的级别
            LOG_CONF['loggers']['biliup']['level'] = args.verbose
            # 更新日志配置中的root的级别
            LOG_CONF['root']['level'] = args.verbose
        # 根据配置字典LOG_CONF配置日志系统
        logging.config.dictConfig(LOG_CONF)
        # 为httpx的日志记录器添加过滤器，用于调试级别的日志
        logging.getLogger('httpx').addFilter(DebugLevelFilter())

        # 注释掉的代码，原本用于设置hpack的日志级别为CRITICAL
        # logging.getLogger('hpack').setLevel(logging.CRITICAL)
        # 注释掉的代码，原本用于设置httpx的日志级别为CRITICAL
        # logging.getLogger('httpx').setLevel(logging.CRITICAL)

    # 判断当前操作系统是否为Windows
    if platform.system() == 'Windows':
        # 如果是Windows系统，并且命令是stop，则直接返回
        if is_stop:
            return
        # 在Windows系统下，直接运行主函数main，并将结果返回
        return asyncio.run(main(args))
    # 调用args中保存的函数的处理函数
    args.func()



async def main(args):
    from biliup.app import event_manager

    event_manager.start()

    # 启动时删除临时文件夹
    shutil.rmtree('./cache/temp', ignore_errors=True)

    # 获取检查源代码的间隔时间
    interval = config.get('check_sourcecode', 15)

    if not args.no_http:
        import biliup.web
        runner = await biliup.web.service(args)
        # 创建自动重载对象，监听事件管理器，清理资源，并设置间隔时间
        detector = AutoReload(event_manager, runner.cleanup, interval=interval)
        # 将自动重载对象设置为全局重载器
        biliup.common.reload.global_reloader = detector
        # 启动自动重载对象
        await detector.astart()
    else:
        import biliup.common.reload
        # 创建自动重载对象，监听事件管理器，并设置间隔时间
        detector = AutoReload(event_manager, interval=interval)
        # 将自动重载对象设置为全局重载器
        biliup.common.reload.global_reloader = detector
        # 启动自动重载对象
        await asyncio.gather(detector.astart())



class GracefulExit(SystemExit):
    # 定义一个GracefulExit类，继承自SystemExit类
    # 为GracefulExit类添加一个属性code，并赋值为1
    code = 1



if __name__ == '__main__':
    arg_parser()
