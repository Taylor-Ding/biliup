import multiprocessing as mp
import time
from typing import List

import stream_gears

from ..engine import Plugin
from ..engine.upload import UploadBase, logger


@Plugin.upload(platform="biliup-rs")
class BiliWeb(UploadBase):
    def __init__(
            self, principal, data, submit_api=None, copyright=2, postprocessor=None, dtime=None,
            dynamic='', lines='AUTO', threads=3, tid=122, tags=None, cover_path=None, description='',
            dolby=0, hires=0, no_reprint=0, open_elec=0, credits=None,
            user_cookie='cookies.json', copyright_source=None
    ):
        super().__init__(principal, data, persistence_path='bili.cookie', postprocessor=postprocessor)
        if tags is None:
            tags = []
        else:
            tags = [str(tag).format(streamer=self.data['name']) for tag in tags]
        self.lines = lines
        self.submit_api = submit_api
        self.threads = threads
        self.tid = tid
        self.tags = tags
        if cover_path:
            self.cover_path = cover_path
        elif "live_cover_path" in self.data:
            self.cover_path = self.data["live_cover_path"]
        else:
            self.cover_path = None
        self.desc = description
        self.credits = credits if credits else []
        self.dynamic = dynamic
        self.copyright = copyright
        self.dtime = dtime
        self.dolby = dolby
        self.hires = hires
        self.no_reprint = no_reprint
        self.open_elec = open_elec
        self.user_cookie = user_cookie
        self.copyright_source = copyright_source

    def upload(self, file_list: List[UploadBase.FileInfo]) -> List[UploadBase.FileInfo]:
        if self.credits:
            # 如果有积分，则调用creditsToDesc_v2方法，将积分转换为描述信息
            desc_v2 = self.creditsToDesc_v2()
        else:
            # 如果没有积分，则创建一个包含描述信息的字典列表
            desc_v2 = [{
                "raw_text": self.desc,
                "biz_id": "",
                "type": 1
            }]

        # 创建一个管道对象，用于进程间通信
        ex_parent_conn, ex_child_conn = mp.Pipe()

        # 创建一个字典，用于存储上传所需的参数
        upload_args = {
            "ex_conn": ex_child_conn,
            "lines": self.lines,
            "video_path": [file.video for file in file_list],
            "cookie_file": self.user_cookie,
            "title": self.data["format_title"][:80],
            "tid": self.tid,
            "tag": ','.join(self.tags),
            "copyright": self.copyright,
            "source": self.copyright_source if self.copyright_source else self.data["url"],
            "desc": self.desc,
            "dynamic": self.dynamic,
            "cover": self.cover_path if self.cover_path is not None else "",
            "dolby": self.dolby,
            "lossless_music": self.hires,
            "no_reprint": self.no_reprint,
            "open_elec": self.open_elec,
            "limit": self.threads,
            "desc_v2": desc_v2,
            # 如果设置了dtime，则将其转换为时间戳并添加到上传参数中，否则为None
            "dtime": int(time.time() + self.dtime) if self.dtime else None,
        }

        # 创建一个子进程，并设置目标函数为stream_gears_upload，同时传入上传参数
        upload_process = mp.get_context('spawn').Process(target=stream_gears_upload, daemon=True, kwargs=upload_args)
        # 启动子进程
        upload_process.start()
        # 等待子进程执行完毕
        upload_process.join()

        # 检查管道中是否有数据
        if ex_parent_conn.poll():
            # 如果有数据，则接收数据并抛出RuntimeError异常
            raise RuntimeError(ex_parent_conn.recv())

        # 记录上传成功的日志信息
        logger.info(f"上传成功: {self.principal}")
        return file_list


    def creditsToDesc_v2(self):
        desc_v2 = []
        desc_v2_tmp = self.desc
        for credit in self.credits:
            try:
                # 查找@credit的位置
                num = desc_v2_tmp.index("@credit")
                # 添加原始文本到desc_v2列表中
                desc_v2.append({
                    "raw_text": " " + desc_v2_tmp[:num],
                    "biz_id": "",
                    "type": 1
                })
                # 添加credit信息到desc_v2列表中
                desc_v2.append({
                    "raw_text": credit["username"],
                    "biz_id": str(credit["uid"]),
                    "type": 2
                })
                # 替换@credit为credit["username"]
                self.desc = self.desc.replace(
                    "@credit", "@" + credit["username"] + "  ", 1)
                # 更新desc_v2_tmp为替换后的剩余部分
                desc_v2_tmp = desc_v2_tmp[num + 7:]
            except IndexError:
                # 如果@credit占位符数量少于credits数量，记录错误日志
                logger.error('简介中的@credit占位符少于credits数量,替换失败')
        # 添加剩余文本到desc_v2列表中
        desc_v2.append({
            "raw_text": " " + desc_v2_tmp,
            "biz_id": "",
            "type": 1
        })
        # 去除开头多余的空格
        desc_v2[0]["raw_text"] = desc_v2[0]["raw_text"][1:]  # 开头空格会导致识别简介过长
        return desc_v2


def stream_gears_upload(ex_conn, lines, *args, **kwargs):
    try:
        # 根据lines的值设置kwargs['line']的值
        if lines == 'bda':
            kwargs['line'] = stream_gears.UploadLine.Bda
        elif lines == 'bda2':
            kwargs['line'] = stream_gears.UploadLine.Bda2
        elif lines == 'ws':
            kwargs['line'] = stream_gears.UploadLine.Ws
        elif lines == 'qn':
            kwargs['line'] = stream_gears.UploadLine.Qn
        elif lines == 'tx':
            kwargs['line'] = stream_gears.UploadLine.Tx
        elif lines == 'txa':
            kwargs['line'] = stream_gears.UploadLine.Txa
        elif lines == 'bldsa':
            kwargs['line'] = stream_gears.UploadLine.Bldsa

        # 调用stream_gears.upload函数进行上传操作
        stream_gears.upload(*args, **kwargs)
    except Exception as e:
        # 若出现异常，将异常信息通过ex_conn发送出去
        ex_conn.send(e)

