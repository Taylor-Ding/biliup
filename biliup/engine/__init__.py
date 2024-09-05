from .decorators import Plugin


def invert_dict(d: dict):
    # 创建一个空字典用于存储反转后的键值对
    inverse_dict = {}
    # 遍历输入字典的每个键值对
    for k, v in d.items():
        # 判断值是否为列表类型
        if isinstance(v, list):
            # 如果是列表，遍历列表中的每个元素
            for item in v:
                # 将元素作为键，原始键作为值存入反转字典
                inverse_dict[item] = k
        else:
            # 如果不是列表，直接将值作为键，原始键作为值存入反转字典
            inverse_dict[v] = k
    # 返回反转后的字典
    return inverse_dict


"""
__all__ 是一个特殊的列表，
用于定义当使用 from module import * 语句时，从模块中导入哪些名称。
在这里，__all__ 被赋值为一个包含两个字符串的列表，分别是 'invert_dict' 和 'Plugin'。
这意味着当其他模块使用 from module import * 导入这个模块时，只会导入 invert_dict 和 Plugin 这两个名称。
"""
__all__ = ['invert_dict', 'Plugin']

