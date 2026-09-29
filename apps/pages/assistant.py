"""
Provide curated platform help and conservative local question matching

Answers follow README.md and the bundled MiMeDat required field profile.
This catalogue uses no model service and never reads data objects itself.
"""

import re
import unicodedata

from django.conf import settings
from django.urls import reverse


CATEGORIES = {
    "upload": "Upload help",
    "search": "Search help",
    "sharing": "Access and sharing help",
    "manage": "My Data help",
    "charts": "Charts help",
    "object": "Current object help",
}

TOPICS = (
    {
        "id": "upload.start", "question": "How do I upload JSON files?",
        "patterns": ("upload", "uploading", "上传"),
        "answer": "Open Upload, select your JSON files, then submit them once. A file may contain one object "
                  "or a collection of objects. Checking shows validation progress; Saving is provisional. "
                  "Uploaded confirms that the entire file was saved. Keep the page open during transfer.",
        "route": "upload_json", "link": "Open Upload",
    },
    {
        "id": "upload.errors", "question": "Why was my upload rejected?",
        "patterns": ("upload failed", "upload rejected", "upload reject", "upload error", "upload empty", "file rejected", "empty", "上传失败", "上传错误", "空值"),
        "answer": "Read the corrections below the upload form: Add means a required field is missing; "
                  "Fill in means it is empty. Expand an object's details for the affected fields. "
                  "Any validation, identifier or sharing error rejects the entire file. Valid other files "
                  "can still be saved. Fix and resubmit only failed files. This assistant does not inspect "
                  "your selected files or diagnose the current upload report.",
        "route": "upload_json", "link": "Open Upload",
    },
    {
        "id": "upload.required", "question": "Which fields are required?",
        "patterns": ("required", "missing", "mandatory", "schema", "mimedat", "必填", "缺少字段", "数据格式"),
        "answer": "Uploads check 24 required top-level fields, including phase, plus applicable nested and "
                  "conditional requirements from the bundled MiMeDat profile. This is not full JSON Schema "
                  "validation. Extra fields are allowed. Required nulls, blank text, empty lists and empty "
                  "objects are rejected; zero and false are not empty. An identifier may be omitted and "
                  "will be generated. Follow the field paths in the upload corrections.",
        "route": "upload_json", "link": "Open Upload",
    },
    {
        "id": "upload.identifier", "question": "How do identifiers work?",
        "patterns": ("identifier", "identifiers", "duplicate", "duplicates", "编号", "重复"),
        "answer": "A missing, null or blank identifier is generated automatically using the MiMeDat template's "
                  "8-character hash. A supplied identifier must be text with no surrounding whitespace. "
                  "Generated and supplied identifiers must be unique across stored records and the upload "
                  "batch. A duplicate rejects the entire file; existing data is never overwritten. "
                  "Remove an already uploaded object, or use a unique identifier for a different object.",
        "route": "upload_json", "link": "Open Upload",
    },
    {
        "id": "upload.limits", "question": "What are the upload limits?",
        "patterns": ("limits", "limit", "upload limits", "upload limit", "upload size", "file size", "storage", "quota", "too large", "限制", "大小", "配额"),
        "answer": "", "route": "upload_json", "link": "Open Upload",
    },
    {
        "id": "upload.interrupted", "question": "What if an upload is interrupted?",
        "patterns": ("interrupted", "unconfirmed", "connection", "network", "上传中断", "网络", "未确认"),
        "answer": "Confirmed Uploaded files remain saved. Unconfirmed means the browser did not receive a "
                  "final result. Check My Data and any available upload progress before submitting again. "
                  "The platform does not retry automatically. Saving counts alone do not confirm a file commit.",
        "route": "json_data_list", "link": "Open My Data",
    },
    {
        "id": "search.start", "question": "How do I search for data?",
        "patterns": ("search", "find", "find data", "search phase", "search public", "search private", "search software", "搜索", "查找", "找数据"),
        "answer": "Open Search and enter keywords, or use Advanced Search without a keyword. All entered "
                  "whole words must match; order and case do not matter. Use Phase for copper, Software "
                  "for Abaqus, or Access for Public. Results include your own, public and explicitly shared "
                  "objects. This assistant gives search guidance; it does not run a search for you.",
        "route": "search", "link": "Open Search",
    },
    {
        "id": "search.filters", "question": "How do advanced filters work?",
        "patterns": ("advanced", "filters", "filter", "search filters", "search filter", "advanced search", "grain", "temperature", "筛选", "晶粒", "温度"),
        "answer": "Common filters cover Identifier, Access, Owner (uploaded by), Creator, Software, Phase "
                  "and Title. Data field filters cover preset simulation parameters such as Grain number "
                  "and Global temperature. All conditions must match the same object. Temperature queries "
                  "use kelvin. Owner is the platform uploader; Creator comes from the JSON metadata.",
        "route": "search", "link": "Open Search",
    },
    {
        "id": "sharing.access", "question": "Who can view my data?",
        "patterns": ("access", "public", "private", "permission", "permissions", "view my", "公开", "私有", "权限"),
        "answer": "The owner can always view their data. Public objects are available to signed-in platform "
                  "users. Private objects are visible only to the owner and explicitly shared users. "
                  "Public does not mean anonymous access or permission to reuse the data under any license. "
                  "Only the owner can delete an object.",
        "route": "share", "link": "Open Sharing",
    },
    {
        "id": "sharing.share", "question": "How do I share a private object?",
        "patterns": ("share", "sharing", "share private", "sharing private", "shared with", "username", "共享", "分享", "用户名"),
        "answer": 'In shared_with, use {"access_type": "c", "username": "viewer"} with an existing platform '
                  'username other than your own. With "c" and no username, the object stays private to its '
                  'owner. For public data use {"access_type": "all"} without username. After upload, owners '
                  "can manage sharing on the object's detail page. These snippets describe sharing metadata "
                  "only; a complete upload still needs its required fields.",
        "route": "share", "link": "Open Sharing",
    },
    {
        "id": "manage.list", "question": "Where are my uploaded objects?",
        "patterns": ("my uploads", "where data", "uploaded objects", "我的上传"),
        "answer": "My Data lists your own uploads. Filter by Access, Software, Phase or Creator, then open "
                  "an object to inspect it. Creator is recorded in the JSON and may differ from the uploader. "
                  "Use Shared with me for another user's private objects shared with you. Search includes "
                  "all objects you can access.",
        "route": "json_data_list", "link": "Open My Data",
    },
    {
        "id": "manage.download", "question": "How do I download data?",
        "patterns": ("download", "export", "csv", "下载", "导出"),
        "answer": "Open an accessible object's detail page to download its complete JSON or available curve "
                  "CSV. Selected objects can also be exported from the lists. One selected object exports "
                  "curves as CSV; multiple objects produce a ZIP with one CSV per object. Every selected "
                  "object must be accessible and have exportable curves. JSON downloads preserve stored "
                  "field names, values and array order.",
        "route": "json_data_list", "link": "Open My Data",
    },
    {
        "id": "manage.delete", "question": "How do I delete my data?",
        "patterns": ("delete", "remove", "删除"),
        "answer": "Use the delete controls in My Data or on an object you own. Only the owner can delete "
                  "an object; access to a public or shared object does not allow deletion. Check your "
                  "selection before confirming. This assistant provides instructions and does not delete data.",
        "route": "json_data_list", "link": "Open My Data",
    },
    {
        "id": "charts.overview", "question": "What does Charts show?",
        "patterns": ("charts", "statistics", "统计", "图表"),
        "answer": "Charts summarizes accessible objects. Choose All accessible, My uploads, Public or "
                  "Shared with me. The stress-strain preview shows one object and matching component. "
                  "Click category bars or numeric intervals to refine the selection. Counts describe "
                  "metadata and result availability; they do not establish physical comparability or "
                  "scientific validity.",
        "route": "charts", "link": "Open Charts",
    },
    {
        "id": "charts.curves", "question": "How are curve previews prepared?",
        "patterns": ("equivalent", "curve length", "different lengths", "preview", "等效", "长度不同", "曲线长度"),
        "answer": "Supplied equivalent arrays take precedence. An equivalent may be calculated only when "
                  "its field is absent and all six required components are available. Unequal arrays pair "
                  "by index to the shorter length. Charts previews over 2,400 points may be reduced, with "
                  "the displayed count stated. Complete object exports keep the full arrays. A length "
                  "difference alone does not explain why samples are missing.",
        "route": "charts", "link": "Open Charts",
    },
    {
        "id": "object.summary", "question": "Summarize this data",
        "patterns": ("summarize", "summary", "overview", "总结", "概述"),
        "action": "summary",
    },
    {
        "id": "object.phase", "question": "What phase does this object contain?",
        "patterns": ("phase", "material", "材料", "物相"), "action": "phase",
    },
    {
        "id": "object.software", "question": "Which software produced this object?",
        "patterns": ("software", "软件"), "action": "software",
    },
    {
        "id": "object.boundary", "question": "Explain mechanical_BC",
        "patterns": ("mechanical bc", "boundary", "boundaries", "vertex", "loading", "边界", "载荷"),
        "action": "boundary",
    },
    {
        "id": "object.plots", "question": "What can I plot?",
        "patterns": ("plot", "curve", "stress", "strain", "绘图", "应力", "应变"), "action": "plots",
    },
    {
        "id": "object.access", "question": "How is access set?",
        "patterns": ("access this", "view this", "who this", "谁能看这个"), "action": "access",
    },
    {
        "id": "help.support", "question": "Can I talk to a human?",
        "patterns": ("human", "agent", "live support", "人工", "客服"),
        "answer": "Live support is not available here. This assistant provides prepared platform help "
                  "and basic information about the current object. Choose a help topic below.",
    },
)


def _normalize(text):
    """
    Normalize user wording for literal FAQ matching

    Parameters
    ----------
    text : str
        Question or a known phrase.

    Returns
    -------
    str
        Lowercase words separated by spaces.
    """
    return re.sub(r"[\W_]+", " ", unicodedata.normalize("NFKC", text).casefold()).strip()


def _score(question, pattern):
    """
    Match complete English words or an explicit Chinese phrase

    Parameters
    ----------
    question : str
        Normalized user question.
    pattern : str
        One supported wording pattern.

    Returns
    -------
    int
        Number of matched words or Chinese characters, otherwise zero.
    """
    if re.search(r"[\u3400-\u9fff]", pattern):
        return len(pattern) if pattern in question else 0
    words = pattern.split()
    return len(words) if set(words).issubset(question.split()) else 0


def help_reply(question, has_object=False):
    """
    Resolve a menu selection or conservatively match a prepared answer

    Ties offer candidate questions. Unknown wording returns the help menu.
    Object actions are resolved by the view after its access check.

    Parameters
    ----------
    question : str
        User text or a selected question label.
    has_object : bool, optional
        Whether the view has authorized a current data object.

    Returns
    -------
    dict
        Answer, topic, suggestions, navigation links and optional object action.
    """
    normalized = _normalize(question)
    categories = [label for key, label in CATEGORIES.items() if key != "object" or has_object]
    reply = {"answer": "Choose a help topic below, or enter a short question about the platform.",
             "suggestions": categories, "links": [], "topic": "menu"}
    if normalized in ("browse help topics", "help", "hello", "hi", "帮助", "你好"):
        return reply
    for category, label in CATEGORIES.items():
        if normalized == _normalize(label) and (category != "object" or has_object):
            reply["topic"] = "menu." + category
            reply["answer"] = "Choose a question about " + label.removesuffix(" help").lower() + "."
            reply["suggestions"] = [topic["question"] for topic in TOPICS if topic["id"].startswith(category + ".")]
            return reply

    exact = [topic for topic in TOPICS if normalized == _normalize(topic["question"])]
    candidates = exact
    if not exact:
        highest = 0
        for topic in TOPICS:
            score = max((_score(normalized, pattern) for pattern in topic["patterns"]), default=0)
            if score > highest:
                highest, candidates = score, [topic]
            elif score and score == highest:
                candidates.append(topic)
    if len(candidates) != 1:
        reply["topic"] = None
        reply["answer"] = "I couldn't match that to one help topic. Please choose a question below or try a shorter question."
        if candidates:
            reply["suggestions"] = [topic["question"] for topic in candidates]
        return reply

    topic = candidates[0]
    reply["topic"] = topic["id"]
    reply["answer"] = topic.get("answer", "")
    category = topic["id"].split(".")[0]
    reply["suggestions"] = [entry["question"] for entry in TOPICS
                            if entry["id"].startswith(category + ".") and entry != topic][:3]
    if not reply["suggestions"]:
        reply["suggestions"] = categories
    if "action" in topic:
        if has_object:
            reply["object_action"] = topic["action"]
        else:
            reply["answer"] = "Open a data object's detail page, then ask this question again. I can only summarize the current accessible object."
            reply["links"] = [{"label": "Open Search", "url": reverse("search")}]
    if "route" in topic:
        reply["links"] = [{"label": topic["link"], "url": reverse(topic["route"])}]
    if topic["id"] == "upload.limits":
        reply["answer"] = (
            f"Each submission allows {settings.PILOT_MAX_UPLOAD_FILES} files, "
            f"{settings.PILOT_MAX_UPLOAD_FILE_BYTES / 1024**2:g} MiB per file, "
            f"{settings.PILOT_MAX_UPLOAD_REQUEST_BYTES / 1024**2:g} MiB combined and "
            f"{settings.PILOT_MAX_UPLOAD_OBJECTS:,} objects. "
            f"Stored JSON quota is {settings.PILOT_MAX_USER_JSON_BYTES / 1024**3:g} GiB per user. "
            "Exceeding a batch limit rejects the submission before any files are saved. "
            "A file size or content error rejects that file; other files can still be processed."
        )
    return reply
