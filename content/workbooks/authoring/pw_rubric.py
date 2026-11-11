"""Analytic rubric and learner workflow for the productive workbook
(synthetic, unreviewed). The rubric is for self-assessment and discussion:
it yields no score, no level and no certified judgment."""

LEVELS = [
    {"id": "not_yet", "fr": "Pas encore", "en": "Not yet", "zh": "尚未达到"},
    {"id": "developing", "fr": "En progrès", "en": "Developing", "zh": "进步中"},
    {"id": "secure", "fr": "Acquis", "en": "Secure", "zh": "已掌握"},
]


def C(cid, fr, en, zh, applies, descriptors):
    """descriptors: {level id: (en, zh)}"""
    return {"id": cid, "fr": fr, "en": en, "zh": zh, "applies_to": applies,
            "descriptors": {k: {"en": a, "zh": b} for k, (a, b) in descriptors.items()}}


CRITERIA = [
    C("task", "Réalisation de la tâche", "Task completion", "任务完成度", ["writing", "speaking"], {
        "not_yet": ("Two or more content points are missing or unclear.", "有两个或以上的内容要点缺失或不清楚。"),
        "developing": ("Every point is attempted; one is thin or hard to find.", "每个要点都有涉及，但有一个内容单薄或不易找到。"),
        "secure": ("Every point is covered clearly, within the length asked.", "所有要点都清楚地完成，长度符合要求。")}),
    C("organisation", "Organisation et cohérence", "Organisation and coherence", "结构与连贯", ["writing", "speaking"], {
        "not_yet": ("Ideas are listed without links; the reader has to guess the order.", "想法罗列在一起，缺少衔接，读者需要猜测顺序。"),
        "developing": ("A clear opening and closing; some links (et, mais, parce que) are repeated.", "开头和结尾清楚；有一些连接词，但重复较多。"),
        "secure": ("A logical order with varied links (d'abord, ensuite, donc, par contre).", "顺序合理，连接词丰富多样。")}),
    C("vocabulary", "Lexique", "Vocabulary", "词汇", ["writing", "speaking"], {
        "not_yet": ("Frequent gaps or words from another language block the meaning.", "常有词汇空缺或夹杂外语词，影响理解。"),
        "developing": ("Everyday words are right; some repetition or approximate choices.", "日常词汇使用正确，但有重复或用词不够准确。"),
        "secure": ("Words fit the topic; the useful expressions of the unit are used correctly.", "用词贴合话题，能正确使用本单元的常用表达。")}),
    C("grammar", "Correction grammaticale", "Grammatical accuracy", "语法准确性", ["writing", "speaking"], {
        "not_yet": ("Errors in basic forms (agreement, auxiliaries, articles) often change the meaning.", "基础形式（配合、助动词、冠词）错误频繁，常影响意思。"),
        "developing": ("Basic forms are mostly right; errors appear in longer sentences.", "基础形式大多正确，长句中会出现错误。"),
        "secure": ("Errors are rare and do not disturb the reader or listener.", "错误很少，不影响读者或听者理解。")}),
    C("register", "Adéquation à la situation", "Register and politeness", "语域与礼貌", ["writing", "speaking"], {
        "not_yet": ("tu/vous, greeting or closing do not fit the person addressed.", "tu/vous、称呼或结尾与对象不符。"),
        "developing": ("Register is right overall but slips once (for example tu then vous).", "整体语域正确，但有一次不一致（如先用 tu 后用 vous）。"),
        "secure": ("Greeting, register and closing fit the situation throughout.", "称呼、语域和结尾始终符合情境。")}),
    C("delivery", "Aisance (transcription)", "Flow, as seen in a transcript", "流畅度（基于文字稿）", ["speaking"], {
        "not_yet": ("Long breaks or restarts make the message hard to follow.", "长时间停顿或反复重来，使信息难以理解。"),
        "developing": ("Some hesitation (euh…) but the message continues.", "有一些犹豫（euh…），但信息能继续传达。"),
        "secure": ("The message flows; self-corrections are quick.", "表达流畅，自我纠正迅速。")}),
]

NOTICE = {
    "en": ("The rubric supports self-assessment and conversation with a teacher. It gives no score and no level. "
           "A transcript cannot show pronunciation, so the speaking criteria judge only what was said."),
    "zh": "本评价表用于自我评估和与教师讨论，不给出分数或等级。文字稿无法体现发音，因此口语标准只评价说话内容。",
}

WORKFLOW = [
    {"step": "write", "en": "Write your answer in the Writing view (create the task with the provided body, then save a draft).",
     "zh": "在写作页面作答（用提供的内容创建任务，然后保存草稿）。"},
    {"step": "feedback", "en": "Ask for feedback only if you choose to, with one click; with the provider disabled there is none, and nothing is scored.",
     "zh": "只有在你主动点击时才请求反馈；若未启用服务则没有反馈，也不会打分。"},
    {"step": "revise", "en": "Save a new version after revising; each version is kept.", "zh": "修改后保存新版本，每个版本都会保留。"},
    {"step": "capture", "en": "If a mistake is worth keeping, record it yourself as a capture (source manual). Nothing is recorded automatically.",
     "zh": "如果某个错误值得记录，请自己把它保存为一条记录（source: manual）。系统不会自动记录。"},
    {"step": "extract", "en": "Extraction of knowledge units runs only when you start it, and only if it is enabled.",
     "zh": "知识点提取只有在你启动且已启用时才会运行。"},
    {"step": "notebook", "en": "Add an item to the Mistake Notebook only by your own action. A recorded mistake is not a sign of mastery or of acceptance.",
     "zh": "只有你自己操作才会加入错题本。被记录的错误既不代表已掌握，也不代表已被认可。"},
]
