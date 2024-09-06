import time

import stream_gears
from typing import List

from ..engine import Plugin
from ..engine.upload import UploadBase, logger


@Plugin.upload(platform="stream_gears")
class BiliWeb(UploadBase):
    def __init__(
            # 初始化函数，接收多个参数
            self, principal, data, submit_api=None, copyright=2, postprocessor=None, dtime=None,
            dynamic='', lines='AUTO', threads=3, tid=122, tags=None, cover_path=None, description='',
            dolby=0, hires=0, no_reprint=0, open_elec=0, credits=None,
            user_cookie='cookies.json', copyright_source=None
    ):
        # 调用父类的初始化方法，传递参数
        super().__init__(principal, data, persistence_path='bili.cookie', postprocessor=postprocessor)

        # 如果credits为空，则初始化为空列表
        if credits is None:
            credits = []

        # 如果tags为空，则初始化为空列表
        if tags is None:
            tags = []

        # 设置self.lines的值
        self.lines = lines

        # 设置self.submit_api的值
        self.submit_api = submit_api

        # 设置self.threads的值
        self.threads = threads

        # 设置self.tid的值
        self.tid = tid

        # 设置self.tags的值
        self.tags = tags

        # 如果cover_path不为空，则设置self.cover_path的值为cover_path
        if cover_path:
            self.cover_path = cover_path
        # 如果cover_path为空，但self.data中存在"live_cover_path"键，则设置self.cover_path的值为self.data["live_cover_path"]
        elif "live_cover_path" in self.data:
            self.cover_path = self.data["live_cover_path"]
        else:
            # 否则设置self.cover_path的值为None
            self.cover_path = None

        # 设置self.desc的值
        self.desc = description

        # 设置self.credits的值
        self.credits = credits

        # 设置self.dynamic的值
        self.dynamic = dynamic

        # 设置self.copyright的值
        self.copyright = copyright

        # 设置self.dtime的值
        self.dtime = dtime

        # 设置self.dolby的值
        self.dolby = dolby

        # 设置self.hires的值
        self.hires = hires

        # 设置self.no_reprint的值
        self.no_reprint = no_reprint

        # 设置self.open_elec的值
        self.open_elec = open_elec

        # 设置self.user_cookie的值
        self.user_cookie = user_cookie

        # 设置self.copyright_source的值
        self.copyright_source = copyright_source


    def upload(self, file_list) -> List[UploadBase.FileInfo]:
        """
        根据指定的线路和配置上传文件到服务器。

        此方法根据 self.lines 的值选择不同的上传线路，并根据其他配置参数上传文件。
        它还负责处理描述信息（desc_v2）、标签（tag）、版权信息（copyright）等的生成和传递。

        参数:
            file_list: 待上传的文件列表。

        返回:
            一个包含上传文件信息的列表。
        """

        # 根据 self.lines 选择适当的上传线路
        if self.lines == 'kodo':
            line = stream_gears.UploadLine.Kodo
        elif self.lines == 'bda2':
            line = stream_gears.UploadLine.Bda2
        elif self.lines == 'ws':
            line = stream_gears.UploadLine.Ws
        elif self.lines == 'qn':
            line = stream_gears.UploadLine.Qn
        elif self.lines == 'cos':
            line = stream_gears.UploadLine.Cos
        elif self.lines == 'cos-internal':
            line = stream_gears.UploadLine.CosInternal

        # 将 self.tags 列表合并成一个字符串，用逗号分隔
        tag = ','.join(self.tags)

        # 根据 self.credits 决定 desc_v2 的值
        if self.credits:
            desc_v2 = self.creditsToDesc_v2()
        else:
            desc_v2 = [{
                "raw_text": self.desc,
                "biz_id": "",
                "type": 1
            }]

        # 设置 source 值，如果 self.copyright_source 为空，则使用默认值
        source = self.copyright_source if self.copyright_source else "https://github.com/biliup/biliup"

        # 如果设置了 self.cover_path，则使用该路径作为 cover 值，否则为空字符串
        cover = self.cover_path if self.cover_path is not None else ""

        # 根据 self.dtime 设置发布时间，如果未设置，则为 None
        dtime = None
        if self.dtime:
            dtime = int(time.time() + self.dtime)

        # 调用 stream_gears.upload 方法上传文件
        stream_gears.upload(
            file_list,
            self.user_cookie,
            self.data["format_title"][:80],
            self.tid,
            tag,
            self.copyright,
            source,
            self.desc,
            self.dynamic,
            cover,
            self.dolby,
            self.hires,
            self.no_reprint,
            self.open_elec,
            self.threads,
            desc_v2,
            dtime,
            line
        )

        # 上传成功后，记录日志信息
        logger.info(f"上传成功: {self.principal}")

        # 返回上传文件列表
        return file_list


    def creditsToDesc_v2(self):
        # 初始化 desc_v2 列表
        desc_v2 = []
        # 临时存储简介
        desc_v2_tmp = self.desc
        # 遍历 credits 列表
        for credit in self.credits:
            try:
                # 查找 @credit 占位符的索引
                num = desc_v2_tmp.index("@credit")
                # 将简介前面的部分添加到 desc_v2 列表中
                desc_v2.append({
                    "raw_text": " " + desc_v2_tmp[:num],
                    "biz_id": "",
                    "type": 1
                })
                # 将 credit 相关信息添加到 desc_v2 列表中
                desc_v2.append({
                    "raw_text": credit["username"],
                    "biz_id": str(credit["uid"]),
                    "type": 2
                })
                # 将 @credit 替换为 credit 用户名，并保留一个空格
                self.desc = self.desc.replace(
                    "@credit", "@" + credit["username"] + "  ", 1)
                # 更新 desc_v2_tmp 的值为 @credit 后面的内容
                desc_v2_tmp = desc_v2_tmp[num + 7:]
            except ValueError:
                # 如果找不到 @credit 占位符，则记录错误日志
                logger.error('简介中的@credit占位符少于credits的数量,替换失败')
        # 将剩余的简介内容添加到 desc_v2 列表中
        desc_v2.append({
            "raw_text": " " + desc_v2_tmp,
            "biz_id": "",
            "type": 1
        })
        # 去除简介开头的空格
        desc_v2[0]["raw_text"] = desc_v2[0]["raw_text"][1:]  # 开头空格会导致简介过长识别错误
        # 返回最终的 desc_v2 列表
        return desc_v2

