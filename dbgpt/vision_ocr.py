"""vision_ocr.py — 本地多模态两阶段:把聊天消息里的图片用 MiniCPM-V(CPU, ollama)
OCR 成文字,再交给文字 LLM 答题。绕开 DB-GPT 的 ollama proxy(它不传图),
直连 ollama /api/generate 的原生 images:[base64] 字段。

挂载方式:bind-mount 进 site-packages(与 traffic_guard.py 同模式),由 fork 的
base_chat.py 在构建 ModelRequest 时调用 replace_images_with_text()。

环境变量:
  VISION_OCR_ENABLED   true/false,默认 false(关,不介入,原流程)
  VISION_OCR_MODEL     ollama 视觉模型名,默认 minicpm-v
  VISION_OCR_API_URL   ollama 地址,默认 http://ollama:11434
  VISION_OCR_PROMPT    OCR 提示词
  VISION_OCR_TIMEOUT   单张图 OCR 超时秒,默认 300(CPU 跑 8B VLM 慢)
"""
import base64
import logging
import os

import requests

logger = logging.getLogger("vision_ocr")

OCR_ENABLED = os.environ.get("VISION_OCR_ENABLED", "false").lower() in (
    "1",
    "true",
    "yes",
    "on",
)
OCR_MODEL = os.environ.get("VISION_OCR_MODEL", "minicpm-v")
OCR_API_URL = os.environ.get("VISION_OCR_API_URL", "http://ollama:11434").rstrip("/")
OCR_PROMPT = os.environ.get(
    "VISION_OCR_PROMPT",
    "请识别并提取图中所有文字内容,完整、原样输出。只输出识别到的文字,不要解释、不要添加额外说明。",
)
OCR_TIMEOUT = int(os.environ.get("VISION_OCR_TIMEOUT", "300"))


def _base_format(fmt: str) -> str:
    """format 形如 'url' / 'url@image/jpeg' / 'base64@image/png' / 'binary' → 取 '@' 前。"""
    if not fmt:
        return ""
    return fmt.split("@", 1)[0].strip().lower()


def _media_object_bytes(obj) -> bytes:
    """从 MediaObject 取出图片原始字节。obj.data + obj.format(text/url/base64/binary)。"""
    fmt = _base_format(getattr(obj, "format", "") or "")
    data = getattr(obj, "data", None)
    if data is None:
        raise ValueError("MediaObject.data 为空")
    if fmt == "binary":
        if isinstance(data, str):
            return data.encode("utf-8")
        return bytes(data)
    if fmt == "base64":
        return base64.b64decode(data)
    if fmt == "url":
        # DB-GPT 内部 file-serve url(也可能外部 url),拉取原始字节
        resp = requests.get(data, timeout=OCR_TIMEOUT)
        resp.raise_for_status()
        return resp.content
    if fmt == "text":
        # text 格式的 image 不正常,直接返回空
        raise ValueError(f"不支持的 image format: text")
    raise ValueError(f"不支持的 image format: {fmt}")


def ocr_image_bytes(b: bytes) -> str:
    """直连 ollama /api/generate,用 minicpm-v 识图,返回识别到的文字。"""
    payload = {
        "model": OCR_MODEL,
        "prompt": OCR_PROMPT,
        "images": [base64.b64encode(b).decode("ascii")],
        "stream": False,
    }
    resp = requests.post(f"{OCR_API_URL}/api/generate", json=payload, timeout=OCR_TIMEOUT)
    resp.raise_for_status()
    return (resp.json().get("response") or "").strip()


def _is_image_media(c) -> bool:
    """c 是否为 IMAGE 类型的 MediaContent。"""
    try:
        from dbgpt.core.interface.media import MediaContent, MediaContentType

        return isinstance(c, MediaContent) and c.type == MediaContentType.IMAGE
    except Exception:
        return False


def replace_images_with_text(content):
    """content: list[MediaContent] → list[MediaContent],把 IMAGE 换成 OCR 文字 TEXT。

    - OCR_ENABLED=false 或 content 不是 list → 原样返回(不介入)
    - 模块加载失败/单张图 OCR 报错 → 该图降级为 [图片识别失败] 文字,不抛异常
    - 整个函数永不抛异常(base_chat 调用处已有 try/except 兜底,这里也防御)
    """
    if not OCR_ENABLED or not isinstance(content, list):
        return content
    # 延迟 import,避免模块加载失败影响宿主
    try:
        from dbgpt.core.interface.media import MediaContent, MediaContentType, MediaObject
    except Exception as e:
        logger.warning("vision_ocr: 无法 import MediaContent,跳过: %s", e)
        return content

    if not any(_is_image_media(c) for c in content):
        return content  # 没图,不浪费一次 OCR 往返

    new_content = []
    for c in content:
        if not _is_image_media(c):
            new_content.append(c)
            continue
        try:
            b = _media_object_bytes(c.object)
            txt = ocr_image_bytes(b)
            if not txt:
                txt = "[图片识别失败:模型返回空]"
        except Exception as e:
            logger.warning("vision_ocr: 图片识别失败,降级: %s", e)
            txt = f"[图片识别失败:{e}]"
        new_content.append(
            MediaContent(
                type=MediaContentType.TEXT,
                object=MediaObject(data=f"[图片识别结果]\n{txt}", format="text"),
            )
        )
    return new_content
