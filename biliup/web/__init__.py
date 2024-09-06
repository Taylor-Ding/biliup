import asyncio
import socket
import json
import os
import pathlib
import concurrent.futures
import threading

import aiohttp_cors
import requests
import stream_gears
from aiohttp import web
from aiohttp.client import ClientSession
from sqlalchemy import select, update
from sqlalchemy.exc import NoResultFound, MultipleResultsFound
from urllib.parse import urlparse, unquote

import biliup.common.reload
from biliup.config import config
from biliup.plugins.bili_webup import BiliBili, Data
from .aiohttp_basicauth_middleware import basic_auth_middleware
from biliup.database.db import SessionLocal
from biliup.database.models import UploadStreamers, LiveStreamers, Configuration, StreamerInfo
from ..app import logger

try:
    from importlib.resources import files
except ImportError:
    # Try backported to PY<37 `importlib_resources`.
    from importlib_resources import files

BiliBili = BiliBili(Data())

routes = web.RouteTableDef()


async def get_basic_config(request):
    # 初始化响应字典
    res = {
        # 获取配置中的行数
        "line": config.data['lines'],
        # 获取配置中的线程数
        "limit": config.data['threads'],
    }

    # 如果配置中存在toml字段
    if config.data.get("toml"):
        # 将toml字段设为True
        res['toml'] = True
    else:
        # 否则，设置用户信息字典
        res['user'] = {
            # 从配置中获取SESSDATA cookie
            "SESSDATA": config.data['user']['cookies']['SESSDATA'],
            # 从配置中获取bili_jct cookie
            "bili_jct": config.data['user']['cookies']['bili_jct'],
            # 从配置中获取DedeUserID__ckMd5 cookie
            "DedeUserID__ckMd5": config.data['user']['cookies']['DedeUserID__ckMd5'],
            # 从配置中获取DedeUserID cookie
            "DedeUserID": config.data['user']['cookies']['DedeUserID'],
            # 从配置中获取access_token
            "access_token": config.data['user']['access_token'],
        }

    # 返回json格式的响应
    return web.json_response(res)



async def url_status(request):
    # 导入biliup.app中的context模块
    from biliup.app import context
    # 调用context中的KernelFunc对象的get_url_status方法，并返回结果作为json响应
    return web.json_response(context['KernelFunc'].get_url_status())


async def set_basic_config(request):
    # 等待接收请求的json数据，并保存到post_data变量中
    post_data = await request.json()
    # 将post_data中的line字段值赋给config.data中的lines字段
    config.data['lines'] = post_data['line']
    # 如果config.data中的lines字段值为'cos'
    if config.data['lines'] == 'cos':
        # 将config.data中的lines字段值修改为'cos-internal'
        config.data['lines'] = 'cos-internal'
    # 将post_data中的limit字段值赋给config.data中的threads字段
    config.data['threads'] = post_data['limit']
    # 如果config.data中不存在toml字段
    if not config.data.get("toml"):
        # 创建一个字典cookies，用于保存用户的cookie信息
        cookies = {
            # 将post_data中user字段下的SESSDATA字段值转为字符串后保存到cookies字典中
            "SESSDATA": str(post_data['user']['SESSDATA']),
            # 将post_data中user字段下的bili_jct字段值转为字符串后保存到cookies字典中
            "bili_jct": str(post_data['user']['bili_jct']),
            # 将post_data中user字段下的DedeUserID__ckMd5字段值转为字符串后保存到cookies字典中
            "DedeUserID__ckMd5": str(post_data['user']['DedeUserID__ckMd5']),
            # 将post_data中user字段下的DedeUserID字段值转为字符串后保存到cookies字典中
            "DedeUserID": str(post_data['user']['DedeUserID']),
        }
        # 将cookies字典保存到config.data中user字段下的cookies字段中
        config.data['user']['cookies'] = cookies
        # 将post_data中user字段下的access_token字段值转为字符串后保存到config.data中user字段下的access_token字段中
        config.data['user']['access_token'] = str(post_data['user']['access_token'])
    # 返回状态码为200的json响应
    return web.json_response({"status": 200})



async def get_streamer_config(request):
    # 返回流配置信息
    return web.json_response(config.data['streamers'])


async def set_streamer_config(request):
    post_data = await request.json()
    # 遍历 post_data 中的 streamers 字典，更新 config.data 中的 streamers 字典
    # config.data['streamers'] = post_data['streamers']
    for i, j in post_data['streamers'].items():
        if i not in config.data['streamers']:
            config.data['streamers'][i] = {}
        for key, Value in j.items():
            config.data['streamers'][i][key] = Value

    # 删除 config.data 中不再存在于 post_data 中的 streamers 字典项
    for i in config.data['streamers']:
        if i not in post_data['streamers']:
            del config.data['streamers'][i]

    # 返回状态码为 200 的 json 响应
    return web.json_response({"status": 200}, status=200)


async def save_config(request):
    # 保存配置
    config.save()
    # 触发全局重载器
    biliup.common.reload.global_reloader.triggered = True

    # 导入 logging 模块
    import logging
    # 创建一个名为 'biliup' 的日志记录器
    logger = logging.getLogger('biliup')
    # 记录一条日志信息，表示配置已保存，将在进程空闲时重启
    logger.info("配置保存，将在进程空闲时重启")

    # 返回状态码为 200 的 json 响应
    return web.json_response({"status": 200}, status=200)


async def root_handler(request):
    # 重定向到 '/index.html'
    return web.HTTPFound('/index.html')



async def cookie_login(request):
    # 如果配置文件中存在toml字段
    if config.data.get("toml"):
        print("trying to login by cookie")
        try:
            # 尝试使用cookies登录
            stream_gears.login_by_cookies()
        except Exception as e:
            # 如果登录失败，则返回400状态码及错误信息
            return web.HTTPBadRequest(text="login failed" + str(e))
    else:
        # 否则，从配置文件中获取cookies
        cookie = config.data['user']['cookies']
        try:
            # 尝试使用cookies登录
            BiliBili.login_by_cookies(cookie)
        except Exception as e:
            # 打印异常信息
            print(e)
            # 如果登录失败，则返回400状态码及错误信息
            return web.HTTPBadRequest(text="login failed")
    # 登录成功，返回200状态码及响应体
    return web.json_response({"status": 200})


async def sms_login(request):
    pass


async def sms_send(request):
    # 注释掉的代码：从请求中获取json数据
    # post_data = await request.json()

    pass


@routes.get('/v1/get_qrcode')
async def qrcode_get(request):
    try:
        # 尝试获取二维码信息
        r = eval(stream_gears.get_qrcode())
    except Exception as e:
        # 如果获取二维码失败，则返回400状态码及错误信息
        return web.HTTPBadRequest(text="get qrcode failed")
    # 返回二维码信息作为json响应
    return web.json_response(r)


# 创建一个进程池执行器
pool = concurrent.futures.ProcessPoolExecutor()

@routes.post('/v1/login_by_qrcode')
async def qrcode_login(request):
    # 从请求中获取json数据
    post_data = await request.json()
    try:
        # 获取事件循环
        loop = asyncio.get_event_loop()
        # 在线程池中执行stream_gears.login_by_qrcode方法，并传入json格式的post_data作为参数
        # loop
        task = loop.run_in_executor(pool, stream_gears.login_by_qrcode, (json.dumps(post_data, )))
        # 等待task执行完成，超时时间为180秒
        res = await asyncio.wait_for(task, 180)
        # 将res解析为json格式
        data = json.loads(res)
        # 构造文件名
        filename = f'data/{data["token_info"]["mid"]}.json'
        # 打开文件，将res写入文件
        with open(filename, 'w', encoding='utf-8') as file:
            file.write(res)
        # 返回包含文件名的json响应
        return web.json_response({
            'filename': filename
        })
    except Exception as e:
        # 打印异常信息并记录日志
        logger.exception('login_by_qrcode')
        # 返回400状态码及错误信息
        return web.HTTPBadRequest(text="login failed" + str(e))


async def pre_archive(request):
    # 如果配置文件中存在toml字段
    if config.data.get("toml"):
        # 加载cookies
        config.load_cookies()
    # 从配置文件中获取cookies
    cookies = config.data['user']['cookies']
    # 返回BiliBili.tid_archive(cookies)的json响应
    return web.json_response(BiliBili.tid_archive(cookies))


async def tag_check(request):
    # 检查请求中的标签是否违禁
    if BiliBili.check_tag(request.rel_url.query['tag']):
        # 如果标签不违禁，返回200状态码的json响应
        return web.json_response({"status": 200})
    else:
        # 如果标签违禁，返回400状态码及错误信息
        return web.HTTPBadRequest(text="标签违禁")



@routes.get('/v1/videos')
async def streamers(request):
    # 媒体文件扩展名列表
    media_extensions = ['.mp4', '.flv', '.3gp', '.webm', '.mkv', '.ts']
    # 黑名单列表
    _blacklist = ['next-env.d.ts']

    # 获取文件列表
    file_list = []
    i = 1
    for file_name in os.listdir('.'):
        # 如果文件名在黑名单中，则跳过
        if file_name in _blacklist:
            continue
        # 分割文件名和扩展名
        name, ext = os.path.splitext(file_name)
        # 如果扩展名在媒体文件扩展名列表中
        if ext in media_extensions:
            # 将文件信息添加到列表中
            file_list.append({'key': i, 'name': file_name, 'updateTime': os.path.getmtime(file_name),
                              'size': os.path.getsize(file_name)})
            i += 1

    # 返回文件列表的 JSON 响应
    return web.json_response(file_list)



@routes.get('/v1/streamer-info')
async def streamers(request):
    res = []
    # 使用上下文管理器创建数据库会话
    with SessionLocal() as db:
        # 查询StreamerInfo表中的所有记录
        result = db.scalars(select(StreamerInfo))
        for s_info in result:
            # 将查询结果转换为字典
            streamer_info = s_info.as_dict()
            # 初始化files列表
            streamer_info['files'] = []
            # 遍历s_info的filelist属性
            for file in s_info.filelist:
                # 将file转换为字典
                tmp = file.as_dict()
                # 删除字典中的streamer_info_id键
                del tmp['streamer_info_id']
                # 将tmp添加到streamer_info的files列表中
                streamer_info['files'].append(tmp)
            # 将streamer_info中的date字段转换为时间戳的整数形式
            streamer_info['date'] = int(streamer_info['date'].timestamp())
            # 将streamer_info添加到res列表中
            res.append(streamer_info)
    # 返回res的JSON响应
    return web.json_response(res)


@routes.get('/v1/streamers')
async def streamers(request):
    # 导入biliup.app中的context模块
    from biliup.app import context
    res = []
    # 使用上下文管理器创建数据库会话
    with SessionLocal() as db:
        # 查询LiveStreamers表中的所有记录
        result = db.scalars(select(LiveStreamers))
        for ls in result:
            # 将查询结果转换为字典
            temp = ls.as_dict()
            # 获取url字段的值
            url = temp['url']
            # 初始化status为'Idle'
            status = 'Idle'
            # 如果context中的PluginInfo的url_status字典中url对应的值为1
            if context['PluginInfo'].url_status.get(url) == 1:
                # 将status设置为'Working'
                status = 'Working'
            # 如果context中的url_upload_count字典中url对应的值大于0
            if context['url_upload_count'].get(url, 0) > 0:
                # 将status设置为'Inspecting'
                status = 'Inspecting'
            # 将status添加到temp字典中
            temp['status'] = status
            # 如果temp字典中包含upload_streamers_id键
            if temp.get("upload_streamers_id"):  # 返回 upload_id 而不是 upload_streamers
                # 将upload_streamers_id的值赋给upload_id键
                temp["upload_id"] = temp["upload_streamers_id"]
                # 删除temp字典中的upload_streamers_id键
                temp.pop("upload_streamers_id")
            # 将temp添加到res列表中
            res.append(temp)
    # 返回res的JSON响应
    return web.json_response(res)


@routes.post('/v1/streamers')
async def add_lives(request):
    from biliup.app import context
    # 解析请求中的JSON数据
    json_data = await request.json()
    # 获取JSON数据中的upload_id字段
    uid = json_data.get('upload_id')
    # 创建数据库会话
    with SessionLocal() as db:
        if uid:
            # 根据uid查询UploadStreamers表中的数据
            us = db.get(UploadStreamers, uid)
            # 创建LiveStreamers对象，并传入过滤后的参数和upload_streamers_id
            to_save = LiveStreamers(**LiveStreamers.filter_parameters(json_data), upload_streamers_id=us.id)
        else:
            # 创建LiveStreamers对象，并传入过滤后的参数
            to_save = LiveStreamers(**LiveStreamers.filter_parameters(json_data))
        try:
            # 将to_save对象添加到数据库中
            db.add(to_save)
            # 提交数据库事务
            db.commit()
        # db.flush(to_save)
        # 如果出现异常，则记录日志并返回错误响应
        except Exception as e:
            logger.exception("Error handling request")
            return web.HTTPBadRequest(text=str(e))
        # 从数据库中加载配置
        config.load_from_db(db)
        # 将JSON数据中的remark和url字段添加到PluginInfo中
        context['PluginInfo'].add(json_data['remark'], json_data['url'])
        # 返回to_save对象的字典形式的JSON响应
        return web.json_response(to_save.as_dict())

@routes.delete('/v1/streamers/{id}')
async def streamers(request):
    from biliup.app import context
    # 获取指定id的LiveStreamers对象
    # org = LiveStreamers.get_by_id(request.match_info['id'])
    with SessionLocal() as db:
        # 使用数据库会话获取指定id的LiveStreamers对象
        org = db.get(LiveStreamers, request.match_info['id'])
    # 删除指定id的LiveStreamers对象
    # LiveStreamers.delete_by_id(request.match_info['id'])
        db.delete(org)
        db.commit()
        # 从PluginInfo中删除对应的url
        context['PluginInfo'].delete(org.url)
    return web.HTTPOk()


@routes.get('/v1/upload/streamers')
async def get_streamers(request):
    with SessionLocal() as db:
        # 查询所有UploadStreamers对象
        res = db.scalars(select(UploadStreamers))
        # 将查询结果转换为字典列表并返回
        return web.json_response([resp.as_dict() for resp in res])


@routes.get('/v1/upload/streamers/{id}')
async def streamers_id(request):
    _id = request.match_info['id']
    with SessionLocal() as db:
        # 根据id获取UploadStreamers对象，并转换为字典
        res = db.get(UploadStreamers, _id).as_dict()
        return web.json_response(res)
@routes.put('/v1/upload/streamers')
async def streamers_put(request):
    json_data = await request.json()
    with SessionLocal() as db:
        # 更新UploadStreamers记录
        # 使用db.execute执行更新操作
    # UploadStreamers.update(**json_data)
        db.execute(update(UploadStreamers), [json_data])
        db.commit()
        config.load_from_db(db)
        # 根据id获取UploadStreamers记录的字典形式
        # return web.json_response(UploadStreamers.get_dict(id=json_data['id']))
        return web.json_response(db.get(UploadStreamers, json_data['id']).as_dict())


@routes.get('/v1/users')
async def users(request):
    # 从数据库中查询key为'bilibili-cookies'的Configuration记录
    # records = Configuration.select().where(Configuration.key == 'bilibili-cookies')
    res = []
    with SessionLocal() as db:
        records = db.scalars(
            select(Configuration).where(Configuration.key == 'bilibili-cookies'))

        for record in records:
            res.append({
                'id': record.id,
                'name': record.value,
                'value': record.value,
                'platform': record.key,
            })
    return web.json_response(res)


@routes.post('/v1/users')
async def users(request):
    json_data = await request.json()
    to_save = Configuration(key=json_data['platform'], value=json_data['value'])
    with SessionLocal() as db:
        db.add(to_save)
        # 保存to_save到数据库
        # to_save.save()
        # 刷新数据库，确保to_save已保存
        # db.flush(to_save)
        resp = {
            'id': to_save.id,
            'name': to_save.value,
            'value': to_save.value,
            'platform': to_save.key,
        }
        db.commit()
        return web.json_response([resp])



@routes.put('/v1/configuration')
async def users(request):
    json_data = await request.json()
    with SessionLocal() as db:
        try:
            # 尝试获取数据库中key为'config'的Configuration记录
            # record = Configuration.get(Configuration.key == 'config')
            # 判断是否只有一行空间配置
            # record = db.execute(
            #     select(Configuration).where(Configuration.key == 'config')
            # ).scalar_one()  # 判断是否只有一行空间配置
            record = db.execute(
                select(Configuration).where(Configuration.key == 'config')
            ).scalar_one()
            # 更新记录的value字段为json_data的json字符串
            record.value = json.dumps(json_data)
            # 将修改后的记录保存回数据库（注：此处代码未执行保存操作，可能是遗漏）
            # db.flush(record)
            # 将记录转换为字典形式
            resp = record.as_dict()
            # 如果需要，可以创建一个新的Configuration对象并设置属性值（注：此处代码未使用，可能是冗余）
            # to_save = Configuration(key='config', value=json.dumps(json_data), id=record.id)
        except NoResultFound:  # 如果数据库中没有key为'config'的记录
            # 创建一个新的Configuration对象，并设置key和value属性为'config'和json_data的json字符串
            to_save = Configuration(key='config', value=json.dumps(json_data))
            # 将新创建的对象添加到数据库中（注：此处代码未执行保存操作，可能是遗漏）
            # to_save.save()
            db.add(to_save)
            db.commit()
            # 将新创建的对象保存回数据库（注：此处代码重复执行了保存操作，可能是冗余）
            # db.flush(to_save)
            # 将新创建的对象转换为字典形式
            resp = to_save.as_dict()
        except MultipleResultsFound as e:  # 如果数据库中存在多个key为'config'的记录
            # 返回状态码为500的json响应，并携带错误信息
            return web.json_response({"status": 500, 'error': f"有多个空间配置同时存在: {e}"}, status=500)
        # 提交数据库事务
        db.commit()
        # 从数据库中加载配置信息（注：此处代码可能需要根据实际情况调整）
        config.load_from_db(db)
    return web.json_response(resp)

@routes.post('/v1/uploads')
async def m_upload(request):
    # 导入biliup_uploader模块
    from ..uploader import biliup_uploader
    # 从请求中获取json数据
    json_data = await request.json()
    # 修改json_data中的uploader字段为'stream_gears'
    json_data['params']['uploader'] = 'stream_gears'
    # 修改json_data中的name字段为template_name字段的值
    json_data['params']['name'] = json_data['params']['template_name']
    # 创建一个线程，目标函数为biliup_uploader，参数为json_data中的files和params字段的值
    threading.Thread(target=biliup_uploader, args=(json_data['files'], json_data['params'])).start()
    # 返回状态为'ok'的json响应
    return web.json_response({'status': 'ok'})


@routes.post('/v1/dump')
async def dump_config(request):
    # 从请求中获取json数据
    json_data = await request.json()
    # 创建一个数据库会话
    with SessionLocal() as db:
        # 从数据库中加载配置信息
        config.load_from_db(db)
    # 调用config的dump方法，参数为json_data中的path字段的值，将配置信息导出到文件中，并返回文件路径
    file = config.dump(json_data['path'])
    # 返回包含文件路径的json响应
    return web.json_response({'path': file})


@routes.get('/v1/status')
async def app_status(request):
    # 导入需要的模块和类
    from biliup.app import context
    from biliup.config import Config
    from biliup.app import PluginInfo
    from biliup import __version__
    # 初始化一个字典res，用于存储返回的结果
    res = {'version': __version__, }
    # 遍历context字典中的键值对
    for key, value in context.items():  # 遍历删除不能被 json 序列化的键值对
        # 如果value是Config类型，则跳过该键值对
        if isinstance(value, Config):
            continue
        # 如果value是PluginInfo类型，则跳过该键值对
        if isinstance(value, PluginInfo):
            continue
        # 将键值对添加到res字典中
        res[key] = value
    # 返回包含应用状态的json响应
    return web.json_response(res)

@routes.get('/bili/archive/pre')
async def pre_archive(request):
    # 定义一个变量 path，并尝试从数据库中获取 'bilibili-cookies' 的配置信息
    # 如果获取成功，则将配置信息的值赋给 path
    # path = 'cookies.json'
    # conf = Configuration.get_or_none(Configuration.key == 'bilibili-cookies')
    with SessionLocal() as db:
        # 从数据库中查询 key 为 'bilibili-cookies' 的 Configuration 记录，并获取其 value 值
        # 如果有多个记录，则 confs 会包含所有记录的 value 值
        # 如果 confs 为空，则不会执行 for循环
        confs = db.scalars(
            select(Configuration).where(Configuration.key == 'bilibili-cookies'))

        # 遍历 confs 列表中的每个元素（即每个 Configuration 记录的 value 值）
        # 逐个尝试使用每个 value 值作为 path 加载 cookies，并调用 BiliBili.tid_archive 函数
        # 如果函数返回的结果中的 code 不等于 0，则跳过当前循环，继续下一个循环
        # 如果函数返回的结果中的 code 等于 0，则返回结果作为 JSON 响应
        # 如果在加载 cookies 或调用函数过程中出现异常，则记录异常并跳过当前循环，继续下一个循环
        # 如果所有循环都执行完毕且没有找到可用的 cookies，则返回状态码为 500 的 JSON 响应，表示无可用 cookie 文件
        # if conf is not None:
        #     path = conf.value
        for conf in confs:
            path = conf.value
            try:
                # 加载指定路径的 cookies
                config.load_cookies(path)
                # 获取加载的 cookies 中的 user 字段下的 cookies 值
                cookies = config.data['user']['cookies']
                # 调用 BiliBili.tid_archive 函数，传入 cookies 作为参数
                res = BiliBili.tid_archive(cookies)
                # 如果函数返回结果中的 code 不等于 0，则跳过当前循环，继续下一个循环
                if res['code'] != 0:
                    continue
                # 返回函数返回结果作为 JSON 响应
                return web.json_response(res)
            except:
                # 记录异常信息
                logger.exception('pre_archive')
                # 跳过当前循环，继续下一个循环
                continue
    # 如果所有循环都执行完毕且没有找到可用的 cookies，则返回状态码为 500 的 JSON 响应，表示无可用 cookie 文件
    return web.json_response({"status": 500, 'error': "无可用 cookie 文件"}, status=500)


@routes.get('/bili/space/myinfo')
async def myinfo(request):
    # 从请求中获取 'user' 参数的值，作为 file 变量
    file = request.query['user']
    try:
        # 尝试加载指定路径的 cookies
        config.load_cookies(file)
    except FileNotFoundError:
        # 如果文件不存在，则返回状态码为 500 的 JSON 响应，并包含错误信息
        return web.json_response({"status": 500, 'error': f"{file} 文件不存在"}, status=500)
    # 获取加载的 cookies 中的 user 字段下的 cookies 值
    cookies = config.data['user']['cookies']
    # 调用 BiliBili.myinfo 函数，传入 cookies 作为参数，并返回函数返回结果作为 JSON 响应
    return web.json_response(BiliBili.myinfo(cookies))

@routes.get('/bili/proxy')
async def proxy(request):
    # 从请求中获取并解码url参数
    url = unquote(request.query['url'])
    # 解析url
    parsed_url = urlparse(url)

    # 如果解析后的url没有主机名或者主机名不以'.hdslb.com'结尾
    if not parsed_url.hostname or not parsed_url.hostname.endswith('.hdslb.com'):
        # 返回禁止访问的HTTP响应
        return web.HTTPForbidden(reason="Access to the requested domain is forbidden")

    # 创建一个异步客户端会话
    async with ClientSession() as session:
        try:
            # 发送GET请求并获取响应
            async with session.get(url) as response:
                # 读取响应内容
                content = await response.read()
                # 返回带有响应内容的HTTP响应
                return web.Response(body=content, status=response.status)
        except Exception as e:
            # 如果发生异常，返回带有异常信息的HTTP响应
            return web.HTTPBadRequest(reason=str(e))


def find_all_folders(directory):
    result = []
    # 遍历指定目录下的所有文件夹和子文件夹
    for foldername, subfolders, filenames in os.walk(directory):
        # 遍历子文件夹
        for subfolder in subfolders:
            # 将相对路径添加到结果列表中
            result.append(os.path.relpath(os.path.join(foldername, subfolder), directory))
    return result

async def service(args):
    # 创建一个web应用对象
    app = web.Application()
    # 添加路由
    app.add_routes([
        # 检查标签
        web.get('/api/check_tag', tag_check),
        # 检查URL状态
        web.get('/url-status', url_status),
        # 获取基本配置
        web.get('/api/basic', get_basic_config),
        # 设置基本配置
        web.post('/api/setbasic', set_basic_config),
        # 获取流媒体配置
        web.get('/api/getconfig', get_streamer_config),
        # 设置流媒体配置
        web.post('/api/setconfig', set_streamer_config),
        # 通过cookie登录
        web.get('/api/login_by_cookie', cookie_login),
        # 通过短信登录
        web.get('/api/login_by_sms', sms_login),
        # 发送短信
        web.post('/api/send_sms', sms_send),
        # 保存配置
        web.get('/api/save', save_config),
        # # 获取二维码（已注释）
        # web.get('/api/get_qrcode', qrcode_get),
        # # 通过二维码登录（已注释）
        # web.post('/api/login_by_qrcode', qrcode_login),
        # 预归档
        web.get('/api/archive_pre', pre_archive),
        # 根路径处理
        web.get('/', root_handler)
    ])
    # 创建一个web应用对象
    app = web.Application()
    # 添加路由
    app.add_routes([
        # 检查标签
        web.get('/api/check_tag', tag_check),
        # 检查URL状态
        web.get('/url-status', url_status),
        # 获取基本配置
        web.get('/api/basic', get_basic_config),
        # 设置基本配置
        web.post('/api/setbasic', set_basic_config),
        # 获取流媒体配置
        web.get('/api/getconfig', get_streamer_config),
        # 设置流媒体配置
        web.post('/api/setconfig', set_streamer_config),
        # 通过cookie登录
        web.get('/api/login_by_cookie', cookie_login),
        # 通过短信登录
        web.get('/api/login_by_sms', sms_login),
        # 发送短信
        web.post('/api/send_sms', sms_send),
        # 保存配置
        web.get('/api/save', save_config),
        # # 获取二维码（已注释）
        # web.get('/api/get_qrcode', qrcode_get),
        # # 通过二维码登录（已注释）
        # web.post('/api/login_by_qrcode', qrcode_login),
        # 预归档
        web.get('/api/archive_pre', pre_archive),
        # 根路径处理
        web.get('/', root_handler)
    ])
    # 如果有设置密码
    if args.password:
        # 添加基本认证中间件
        app.middlewares.append(basic_auth_middleware('/', {'biliup': args.password}))

    # cors = aiohttp_cors.setup(app, defaults={
    # 设置CORS跨域设置
    cors = aiohttp_cors.setup(app, defaults={
        "*": aiohttp_cors.ResourceOptions(
            allow_credentials=True,
            allow_methods="*",
            expose_headers="*",
            allow_headers="*"
        )
    })

    # 为每个路由添加CORS跨域设置
    for route in list(app.router.routes()):
        cors.add(route)

    # 根据参数设置是否记录访问日志
    if args.no_access_log:
        runner = web.AppRunner(app, access_log=None)
    else:
        runner = web.AppRunner(app)
    # 设置中间件
    setup_middlewares(app)
    # 初始化应用
    await runner.setup()
    # 监听端口并启动服务
    site = web.TCPSite(runner, host=args.host, port=args.port)
    await site.start()
    # 启动服务后，记录启动日志
    log_startup(args.host, args.port)
    return runner

async def handle_404(request):
    # 返回404页面的FileResponse对象
    return web.FileResponse(files('biliup.web').joinpath('public').joinpath('404.html'))


async def handle_500(request):
    # 返回500错误的json_response对象
    return web.json_response({"status": 500, 'error': "Error handling request"}, status=500)


def create_error_middleware(overrides):
    @web.middleware
    async def error_middleware(request, handler):
        try:
            # 调用处理函数，并等待结果
            return await handler(request)
        except web.HTTPException as ex:
            # 根据异常状态码获取对应的处理函数
            override = overrides.get(ex.status)
            if override:
                # 如果存在对应的处理函数，则调用并等待结果
                return await override(request)

            # 如果不存在对应的处理函数，则重新抛出异常
            raise
        except Exception:
            # 记录异常日志
            request.protocol.logger.exception("Error handling request")
            # 调用500错误处理函数，并等待结果
            return await overrides[500](request)

    # 返回错误处理中间件
    return error_middleware


def setup_middlewares(app):
    # 定义中间件装饰器
    @web.middleware
    async def file_type_check_middleware(request, handler):
        # 允许的文件扩展名集合
        allowed_extensions = {'.mp4', '.flv', '.3gp', '.webm', '.mkv', '.ts', '.xml', '.log'}

        # 如果请求路径以'/static/'开头
        if request.path.startswith('/static/'):
            # 获取文件名
            filename = request.match_info.get('filename')
            if filename:
                # 获取文件扩展名
                extension = '.' + filename.split('.')[-1]
                # 如果文件扩展名不在允许的扩展名集合中
                if extension not in allowed_extensions:
                    # 返回禁止访问的HTTP响应
                    return web.HTTPForbidden(reason="File type not allowed")
        # 调用下一个中间件或处理函数
        return await handler(request)

    # 创建错误处理中间件
    error_middleware = create_error_middleware({
        404: handle_404,
        500: handle_500,
    })
    # 将错误处理中间件添加到应用的中间件列表中
    app.middlewares.append(error_middleware)
    # 将文件类型检查中间件添加到应用的中间件列表中
    app.middlewares.append(file_type_check_middleware)



def log_startup(host, port) -> None:
    """Show information about the address when starting the server."""
    # 初始化消息列表
    messages = ['WebUI 已启动，请浏览器访问']
    # 如果host为空，则默认为"0.0.0.0"
    host = host if host else "0.0.0.0"
    # 设置协议为http
    scheme = "http"
    # 初始化显示的hostname
    display_hostname = host

    # 如果host是"0.0.0.0"或"::"
    if host in {"0.0.0.0", "::"}:
        # 添加消息：正在所有地址上运行（host）
        messages.append(f" * Running on all addresses ({host})")
        # 如果host是"0.0.0.0"
        if host == "0.0.0.0":
            # 设置localhost为"127.0.0.1"
            localhost = "127.0.0.1"
            # 获取IPv4接口IP地址，并赋值给display_hostname
            display_hostname = get_interface_ip(socket.AF_INET)
        else:
            # 设置localhost为"[::1]"
            localhost = "[::1]"
            # 获取IPv6接口IP地址，并赋值给display_hostname
            display_hostname = get_interface_ip(socket.AF_INET6)

        # 添加消息：正在{scheme}://{localhost}:{port}上运行
        messages.append(f" * Running on {scheme}://{localhost}:{port}")

    # 如果display_hostname中包含冒号
    if ":" in display_hostname:
        # 将display_hostname用方括号括起来
        display_hostname = f"[{display_hostname}]"

    # 添加消息：正在{scheme}://{display_hostname}:{port}上运行
    messages.append(f" * Running on {scheme}://{display_hostname}:{port}")

    # 打印所有消息，以换行符分隔
    print("\n".join(messages))



def get_interface_ip(family: socket.AddressFamily) -> str:
    """Get the IP address of an external interface. Used when binding to
    0.0.0.0 or ::1 to show a more useful URL.

    :meta private:
    """
    # 任意私有地址
    # arbitrary private address
    host = "fd31:f903:5ab5:1::1" if family == socket.AF_INET6 else "10.253.155.219"

    with socket.socket(family, socket.SOCK_DGRAM) as s:
        try:
            # 连接到主机和端口
            s.connect((host, 58162))
        except OSError:
            # 如果连接失败，返回本地回环地址
            return "::1" if family == socket.AF_INET6 else "127.0.0.1"

        # 返回套接字绑定的IP地址
        return s.getsockname()[0]  # type: ignore

