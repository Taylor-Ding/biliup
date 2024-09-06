import os
from logging.handlers import TimedRotatingFileHandler
import time
import logging

class SafeRotatingFileHandler(TimedRotatingFileHandler):
    def __init__(self, filename, when='h', interval=1, backupCount=0, encoding=None, delay=False, utc=False):
        # 调用父类TimedRotatingFileHandler的构造函数
        # 初始化TimedRotatingFileHandler对象
        TimedRotatingFileHandler.__init__(self, filename, when, interval, backupCount, encoding, delay, utc)


    """
    Override doRollover
    lines commanded by "##" is changed by cc
    """

    def doRollover(self):
        """
        do a rollover; in this case, a date/time stamp is appended to the filename
        when the rollover happens.  However, you want the file to be named for the
        start of the interval, not the current time.  If there is a backup count,
        then we have to get a list of matching filenames, sort them and remove
        the one with the oldest suffix.

        Override,   1. if dfn not exist then do rename
                    2. _open with "a" model
        """
        if self.stream:
            # 关闭流
            self.stream.close()
            # 将流设置为None
            self.stream = None
        # 获取该序列开始的时间并将其转换为TimeTuple
        # get the time that this sequence started at and make it a TimeTuple
        currentTime = int(time.time())
        # 获取当前时间的夏令时标志
        dstNow = time.localtime(currentTime)[-1]
        # 计算上一次滚动的时间
        t = self.rolloverAt - self.interval
        if self.utc:
            # 如果使用UTC时间，则获取UTC时间的时间元组
            timeTuple = time.gmtime(t)
        else:
            # 获取本地时间的时间元组
            timeTuple = time.localtime(t)
            # 获取上一次滚动时间的夏令时标志
            dstThen = timeTuple[-1]
            # 如果当前时间的夏令时与上一次滚动时间的夏令时不同
            if dstNow != dstThen:
                if dstNow:
                    # 如果当前时间有夏令时，则需要增加一小时
                    addend = 3600
                else:
                    # 如果当前时间没有夏令时，则需要减去一小时
                    addend = -3600
                # 更新时间元组
                timeTuple = time.localtime(t + addend)
        # 根据时间元组生成新的文件名
        dfn = self.baseFilename + "." + time.strftime(self.suffix, timeTuple)
        # 如果新文件名已经存在，则将其删除（已注释）
        ##        if os.path.exists(dfn):
        ##            os.remove(dfn)

        # Issue 18940: 如果delay为True，则可能未创建文件
        # 如果新文件名不存在且基础文件名存在，则将基础文件名重命名为新文件名
        # Issue 18940: A file may not have been created if delay is True.
        ##        if os.path.exists(self.baseFilename):
        if not os.path.exists(dfn) and os.path.exists(self.baseFilename):
            os.rename(self.baseFilename, dfn)
        # 如果设置了备份计数，则删除旧的备份文件
        if self.backupCount > 0:
            for s in self.getFilesToDelete():
                os.remove(s)
        # 如果不使用延迟打开，则设置文件打开模式并打开文件流
        if not self.delay:
            self.mode = "a"
            self.stream = self._open()
        # 计算下一次滚动的时间
        newRolloverAt = self.computeRollover(currentTime)
        # 如果下一次滚动的时间小于等于当前时间，则将下一次滚动时间更新为当前时间加上间隔时间
        while newRolloverAt <= currentTime:
            newRolloverAt = newRolloverAt + self.interval
        # 如果为午夜或每周滚动且不使用UTC时间，则需要根据夏令时调整滚动时间
        # If DST changes and midnight or weekly rollover, adjust for this.
        if (self.when == 'MIDNIGHT' or self.when.startswith('W')) and not self.utc:
            dstAtRollover = time.localtime(newRolloverAt)[-1]
            if dstNow != dstAtRollover:
                if not dstNow:  # DST在下次滚动之前开始，因此需要减去一小时
                    addend = -3600
                else:  # DST在下次滚动之前结束，因此需要增加一小时
                    addend = 3600
                newRolloverAt += addend
        # 更新滚动时间
        self.rolloverAt = newRolloverAt


class DebugLevelFilter(logging.Filter):
    """
    一个日志过滤器，用于阻止除调试级别外的所有日志消息，除非控制台级别设置为调试级别
    """
    def filter(self, record):
        # 判断是否启用了调试级别的日志记录
        return logging.getLogger().isEnabledFor(logging.DEBUG)