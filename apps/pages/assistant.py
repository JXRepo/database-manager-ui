"""
Resolve platform questions and short follow-ups against trusted answers

Local embeddings match meaning; the model never generates factual answers.
"""

import re
import unicodedata
from difflib import get_close_matches

from django.conf import settings
from django.core import signing
from django.urls import reverse

from .assistant_knowledge import CATEGORIES, CATEGORY_ALIASES, EXAMPLES, TOPICS
from .assistant_semantics import ModelUnavailable, rank_topics


TOPIC_BY_ID = {topic["id"]: topic for topic in TOPICS}
CHOICE_LABELS = {"upload.format": "JSON format", "upload.start": "Upload form",
                 "upload.required": "Required fields", "upload.template": "JSON template"}
SEMANTIC_EXAMPLES = tuple((topic["id"], topic["question"]) for topic in TOPICS) + tuple(
    (topic_id, example) for topic_id, examples in EXAMPLES.items() for example in examples
) + tuple(
    (topic["id"], example) for topic in TOPICS for example in topic.get("examples", ())
)
CONTEXT_SALT = "fair-assistant-conversation-v1"
MENU_PAGE_SIZE = 6
CATEGORY_TOPICS = {key: [] for key in CATEGORIES}
for _topic in TOPICS:
    CATEGORY_TOPICS[_topic.get("category", _topic["id"].split(".")[0])].append(_topic["id"])


def _normalize(text):
    """
    Normalize wording for exact labels and short aliases

    Parameters
    ----------
    text : str
        Question or known phrase.

    Returns
    -------
    str
        Lowercase words separated by spaces.
    """
    return re.sub(r"[\W_]+", " ", unicodedata.normalize("NFKC", text).casefold()).strip()


def read_context(token, user_id, object_id):
    """
    Read short-lived topic state bound to this user and object

    Parameters
    ----------
    token : str
        Signed token from the previous response.
    user_id : int
        Authenticated user identifier.
    object_id : int or None
        Independently authorized current object.

    Returns
    -------
    dict
        Verified topic state or an empty conversation.
    """
    if not token:
        return {}
    try:
        state = signing.loads(token, salt=CONTEXT_SALT, max_age=1800)
    except (signing.BadSignature, ValueError, TypeError):
        return {}
    if not isinstance(state, dict) or state.get("user") != user_id or state.get("object") != object_id:
        return {}
    return state.get("conversation", {})


def sign_context(conversation, user_id, object_id):
    """
    Sign only topic identifiers, never questions or object contents

    Parameters
    ----------
    conversation : dict
        Topic and suggested topic identifiers from a prepared reply.
    user_id : int
        Authenticated user identifier.
    object_id : int or None
        Current authorized object identifier.

    Returns
    -------
    str
        Signed state, or an empty token for a reset conversation.
    """
    if not conversation:
        return ""
    return signing.dumps({"user": user_id, "object": object_id, "conversation": conversation},
                         salt=CONTEXT_SALT, compress=True)


def _menu(has_object, answer=None):
    """
    Offer platform categories and clear any previous topic

    Parameters
    ----------
    has_object : bool
        Whether current object help is available.
    answer : str, optional
        Message preceding the categories.

    Returns
    -------
    dict
        Prepared category reply.
    """
    return {
        "answer": answer or "I can help you get started, prepare and upload data, search, share, export, read plots or manage your account. Choose a category or ask in your own words.",
        "suggestions": [label for key, label in CATEGORIES.items() if key != "object" or has_object],
        "links": [], "topic": None if answer else "menu", "conversation": {},
    }


def _page_label(category, page):
    """
    Label a category page so its navigation works without conversation state

    Parameters
    ----------
    category : str
        Maintained category key.
    page : int
        Zero-based page index.

    Returns
    -------
    str
        Visible navigation label.
    """
    pages = (len(CATEGORY_TOPICS[category]) + MENU_PAGE_SIZE - 1) // MENU_PAGE_SIZE
    return f"{CATEGORIES[category]} ({page + 1}/{pages})"


def _category_menu(category, page=0):
    """
    Offer a short page of questions and retain their visible selection order

    Parameters
    ----------
    category : str
        Already authorized help category.
    page : int, optional
        Requested page, bounded to the available questions.

    Returns
    -------
    dict
        Category questions, adjacent page buttons and signed-state input.
    """
    topics = CATEGORY_TOPICS[category]
    last_page = (len(topics) - 1) // MENU_PAGE_SIZE
    page = max(0, min(page, last_page))
    choices = topics[page * MENU_PAGE_SIZE:(page + 1) * MENU_PAGE_SIZE]
    suggestions = [TOPIC_BY_ID[key]["question"] for key in choices]
    if page > 0:
        suggestions.append(_page_label(category, page - 1))
    if page < last_page:
        suggestions.append(_page_label(category, page + 1))
    return {
        "topic": "menu." + category,
        "answer": f"{CATEGORIES[category]} — page {page + 1} of {last_page + 1}. Choose a question, or describe what you need.",
        "suggestions": suggestions, "links": [],
        "conversation": {"category": category, "page": page, "choices": choices},
    }


def _clarify(topic_ids, answer="Which of these would you like help with?"):
    """
    Ask a concrete question with ordered choices for the next turn

    Parameters
    ----------
    topic_ids : sequence of str
        Candidate topic identifiers in display order.
    answer : str, optional
        Clarifying question.

    Returns
    -------
    dict
        Reply containing candidates and minimal conversation state.
    """
    return {"answer": answer, "topic": None, "links": [],
            "suggestions": [CHOICE_LABELS.get(key, TOPIC_BY_ID[key]["question"]) for key in topic_ids],
            "conversation": {"topic": None, "choices": list(topic_ids)}}


def _answer(topic_id, has_object):
    """
    Return a maintained answer or an authorized object action

    Parameters
    ----------
    topic_id : str
        Selected knowledge topic.
    has_object : bool
        Whether an object is already authorized.

    Returns
    -------
    dict
        Prepared answer and useful follow-up choices.
    """
    topic = TOPIC_BY_ID[topic_id]
    reply = {"topic": topic_id, "answer": topic.get("answer", ""), "links": []}
    category = topic.get("category", topic_id.split(".")[0])
    related = list(topic.get("related", [key for key in CATEGORY_TOPICS[category] if key != topic_id][:3]))
    if topic_id in ("upload.format", "upload.template", "upload.start"):
        related = [key for key in ("upload.required", "upload.template", "upload.limits") if key != topic_id]
    reply["suggestions"] = [CHOICE_LABELS.get(key, TOPIC_BY_ID[key]["question"]) for key in related]
    reply["conversation"] = {"topic": topic_id, "choices": related}
    if not reply["suggestions"]:
        reply["suggestions"] = _menu(has_object)["suggestions"]
    if "action" in topic:
        if has_object:
            reply["object_action"] = topic["action"]
        else:
            reply["answer"] = "Open a data object's detail page, then ask this question again. I can only summarize the current accessible object."
            reply["links"] = [{"label": "Open Search", "url": reverse("search")}]
    if "route" in topic:
        reply["links"] = [{"label": topic["link"], "url": reverse(topic["route"])}]
    if topic_id == "upload.limits":
        reply["answer"] = (
            f"Each submission allows {settings.PILOT_MAX_UPLOAD_FILES} files, "
            f"{settings.PILOT_MAX_UPLOAD_FILE_BYTES / 1024**2:g} MiB per file, "
            f"{settings.PILOT_MAX_UPLOAD_REQUEST_BYTES / 1024**2:g} MiB combined and "
            f"{settings.PILOT_MAX_UPLOAD_OBJECTS:,} objects. "
            f"Stored JSON quota is {settings.PILOT_MAX_USER_JSON_BYTES / 1024**3:g} GiB per user. "
            "Exceeding a batch limit rejects the submission before any files are saved. "
            "A file size or content error rejects that file; other files can still be processed."
        )
    elif topic_id == "upload.quota":
        reply["answer"] = (
            f"Your allowance is {settings.PILOT_MAX_USER_JSON_BYTES / 1024**3:g} GiB of currently stored JSON. "
            "It counts compact UTF-8 JSON including generated identifiers, not the original file's byte size. "
            "It is not a monthly allowance. Deleting your own objects frees your quota; keep a JSON backup first. "
            "There is no quota expansion request feature. A personal allowance does not guarantee free space "
            "or memory on the shared hosting service."
        )
    elif topic_id == "upload.rate":
        policy = settings.PILOT_RATE_LIMITS["upload"]
        reply["answer"] = (
            f"Uploads allow {policy['limit']} submissions per {policy['window_seconds'] / 60:g} minutes per user. "
            "Failed submissions also count. Wait for the current window to expire, then correct the errors "
            "before submitting again; repeated clicks do not help. A separate notice about an active upload "
            "means you should return to its progress first. Interrupted or unconfirmed files are not retried automatically."
        )
    return reply


def _correct_typo(text):
    """
    Correct at most one near-miss in a short known platform term

    Parameters
    ----------
    text : str
        Normalized question.

    Returns
    -------
    str
        Question with a conservative spelling correction, if any.
    """
    words = text.split()
    known_typos = {"pasword": "password", "passwrod": "password", "oricd": "orcid", "xslx": "xlsx"}
    for index, word in enumerate(words):
        if word in known_typos:
            words[index] = known_typos[word]
            return " ".join(words)
    if len(words) > 6:
        return text
    vocabulary = set()
    for topic in TOPICS:
        for alias in topic["patterns"]:
            vocabulary.update(word for word in alias.split() if word.isascii() and len(word) >= 5)
    for index, word in enumerate(words):
        if len(word) < 5 or not word.isascii() or word in vocabulary:
            continue
        possible = sorted(candidate for candidate in vocabulary if abs(len(candidate) - len(word)) <= 1)
        close = get_close_matches(word, possible, n=1, cutoff=0.82)
        if close:
            words[index] = close[0]
            break
    return " ".join(words)


def _follow_up(text, context):
    """
    Interpret brief choices only within the verified previous topic

    Parameters
    ----------
    text : str
        Normalized question.
    context : dict
        Verified conversation state.

    Returns
    -------
    str or None
        Selected topic when the follow-up is unambiguous.
    """
    choices = context.get("choices", [])
    ordinals = {"1": 0, "first": 0, "the first one": 0, "第一个": 0,
                "2": 1, "second": 1, "the second one": 1, "第二个": 1,
                "3": 2, "third": 2, "the third one": 2, "第三个": 2,
                "4": 3, "fourth": 3, "the fourth one": 3, "第四个": 3,
                "5": 4, "fifth": 4, "the fifth one": 4, "第五个": 4,
                "6": 5, "sixth": 5, "the sixth one": 5, "第六个": 5}
    position = ordinals.get(text)
    if position is not None and position < len(choices):
        return choices[position]
    topic = context.get("topic") or ""
    if topic.startswith(("upload.", "prepare.")):
        if text in ("how big", "how much", "how many", "and the size", "what about size", "多大", "多少", "大小呢"):
            return "upload.limits"
        if text in ("which fields", "what fields", "and the fields", "哪些字段", "哪些必填"):
            return "upload.required"
        if text in ("csv", "excel", "pdf", "what about csv", "what about excel"):
            return "upload.format"
    if topic == "upload.identifier" and text in ("can i leave it blank", "is it required", "能不填吗"):
        return topic
    if text in ("how", "how do i do that", "怎么设置", "怎么做"):
        if topic in ("sharing.access", "sharing.share"):
            return "sharing.share"
        if topic in ("sharing.revoke", "sharing.visibility"):
            return topic
    if topic == "manage.delete" and text in ("can i undo it", "can i get it back", "能撤销吗", "能恢复吗"):
        return "manage.restore"
    if topic == "account.password" and text in ("what if i forgot it", "i forgot the old one", "那原来的忘了呢", "忘了旧密码呢"):
        return "account.recovery"
    if (topic == "account.orcid_disconnect" or not topic and "account.orcid_disconnect" in choices):
        if text in ("how do i sign in afterwards", "how do i log in after that", "之后还怎么登录", "解绑后怎么登录"):
            return "account.orcid_disconnect"
    return None


def help_reply(question, has_object=False, context=None):
    """
    Match a platform question or clarify it using local sentence embeddings

    Parameters
    ----------
    question : str
        User question or chosen help label.
    has_object : bool, optional
        Whether the view has authorized a current object.
    context : dict, optional
        Verified state from the previous response.

    Returns
    -------
    dict
        Trusted answer or clarification with minimal conversation state.
    """
    text = _correct_typo(_normalize(question))
    context = context or {}
    if text in ("browse help topics", "help", "hello", "hi", "what can you do", "thanks", "thank you", "帮助", "你好", "谢谢",
                "none of these", "none of those", "something else", "neither", "都不是"):
        return _menu(has_object)
    for category, label in CATEGORIES.items():
        if category == "object" and not has_object:
            continue
        if text in {_normalize(alias) for alias in (label, *CATEGORY_ALIASES[category])}:
            return _category_menu(category)
        pages = (len(CATEGORY_TOPICS[category]) + MENU_PAGE_SIZE - 1) // MENU_PAGE_SIZE
        for page in range(pages):
            if text == _normalize(_page_label(category, page)):
                return _category_menu(category, page)
    category = context.get("category")
    if category in CATEGORY_TOPICS and (category != "object" or has_object):
        if text in ("more", "next", "next page", "更多", "下一页"):
            return _category_menu(category, context.get("page", 0) + 1)
        if text in ("back", "previous", "previous page", "返回", "上一页"):
            return _category_menu(category, context.get("page", 0) - 1)
    if (text in ("dataform", "form", "表单", "数据表单")
            or re.search(r"\bdata forms?\b", text)):
        return _clarify(["upload.format", "upload.start"], "Do you mean the JSON data format or the upload form?")
    if text in ("password", "密码"):
        return _clarify(["account.password", "account.recovery", "account.registration"],
                        "Do you want to change a password, recover access, or check the registration requirements?")
    if text == "orcid":
        return _clarify(["account.orcid_connect", "account.orcid_setup", "account.orcid_disconnect"],
                        "Do you want to connect ORCID, finish account setup, or disconnect it?")
    selected = _follow_up(text, context)
    if selected:
        return _answer(selected, has_object)
    for topic in TOPICS:
        labels = (topic["question"], CHOICE_LABELS.get(topic["id"], ""), *topic["patterns"])
        if text in {_normalize(label) for label in labels if label}:
            return _answer(topic["id"], has_object)
    if re.fullmatch(r"(?:(?:the )?(?:first|second|third|fourth|fifth|sixth)(?: one)?|[1-6]|第[一二三四五六]个)", text):
        return _menu(has_object, "Choose a help topic first, then I can follow your selection.")
    words = set(text.split())
    if (((words & {"delete", "remove", "erase"} or "get rid" in text)
            and (words & {"download", "export"} or "a copy" in text))
            or ("删除" in text and any(word in text for word in ("下载", "导出")))):
        return _clarify(["manage.download", "manage.delete"], "Would you like to download data or delete data?")
    try:
        semantic_text = question if text == _normalize(question) else text
        ranked = rank_topics(semantic_text, SEMANTIC_EXAMPLES)
    except ModelUnavailable:
        return _menu(has_object, "Question matching is temporarily unavailable. You can still choose a help topic below.")
    scores = dict(ranked)
    # Specific maintained phrases can separate nearby meanings such as a
    # rejected upload and a lost connection, without matching broad substrings
    for topic in TOPICS:
        for alias in topic["patterns"]:
            phrase = _normalize(alias)
            parts = phrase.split()
            if phrase.isascii():
                specific = len(parts) >= 2 and not set(parts) & {"my", "this", "the", "who", "with"}
                matched = " " + phrase + " " in " " + text + " "
            else:
                specific = len(phrase) >= 4
                matched = phrase in text
            if specific and matched:
                scores[topic["id"]] += 0.08
                break
    if not has_object:
        scores["sharing.access"] = max(scores["sharing.access"], scores.pop("object.access"))
    candidates = sorted(((key, value) for key, value in scores.items() if key != "outside"),
                        key=lambda item: item[1], reverse=True)
    best, score = candidates[0]
    if scores.get("outside", 0) >= max(0.48, score - 0.03) or score < 0.38:
        return _menu(has_object, "I can help with this data platform: file formats, uploads, search, sharing and plots. Choose a topic below.")
    margin = score - candidates[1][1]
    short_unknown = len(text.split()) == 1 and text.isascii()
    if not short_unknown and ((score >= 0.65 and margin >= 0.025) or (score >= 0.55 and margin >= 0.06)
                              or (score >= 0.50 and margin >= 0.12)):
        return _answer(best, has_object)
    if best in ("sharing.access", "sharing.share"):
        choices = ["sharing.access", "sharing.share"]
        nearby = [key for key, value in candidates[:3]
                  if key.startswith("sharing.") and key not in choices and value >= score - 0.12]
        return _clarify(choices + nearby[:1],
                        "Do you want to check who can view data, or change who it is shared with?")
    close = [key for key, value in candidates[:3] if value >= score - 0.12]
    return _clarify(close)
