from app.modules.m8_disclosure.rules import adjudicate


def execute(state):
    # 补录重跑会带着新的 calculations 进入这里，纯函数裁决自动给出新结论。
    return adjudicate(state)
