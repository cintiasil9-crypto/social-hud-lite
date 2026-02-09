from flask import Flask, Response, jsonify, request
import os, time, math, requests, json, re, random
from collections import defaultdict

# =================================================
# APP SETUP
# =================================================

app = Flask(__name__)
GOOGLE_PROFILES_FEED = os.environ["GOOGLE_PROFILES_FEED"]

CACHE = {"profiles": None, "ts": 0}
CACHE_TTL = 300
NOW = time.time()

# ======================================
# SOCIAL TRAIT KEYWORDS — SLANG EXPANDED
# ======================================

ENGAGING = {
    "hi","hey","heya","hiya","yo","sup","wb","welcome",
    "hello","ello","hai","haiii","hii","hiii",
    "o/","\\o","wave","waves","*waves*","*wave*",
    "heyhey","yo yo","sup all","hiya all"
}

CURIOUS = {
    "why","how","what","where","when","who",
    "anyone","anybody","any1","any1?",
    "curious","wonder","wondering",
    "?","??","???","????",
    "huh","eh","hm","hmm","hmmm"
}

HUMOR = {
    "lol","lmao","lmfao","rofl","roflmao",
    "haha","hehe","heh","bahaha",
    "😂","🤣","😆","😜","😹","💀","😭",
    "lawl","lul","lel","ded","im dead","dead 💀"
}

SUPPORT = {
    "sorry","sry","srry","soz",
    "hope","ok","okay","k","kk","mk",
    "there","here","np","nps","no worries",
    "hug","hugs","hugz","*hug*","*hugs*",
    "<3","❤️","💜","💙","💖",
    "u ok","you ok","all good","its ok","it's ok"
}

DOMINANT = {
    "listen","look","stop","wait","now",
    "do it","dont","don't","come here","stay",
    "pay attention","focus","enough",
    "move","sit","stand","follow","watch","hold up"
}

COMBATIVE = {
    "idiot","stupid","dumb","moron","retard",
    "shut","shut up","stfu","gtfo","wtf","tf",
    "screw you","fuck off",
    "trash","garbage","bs","bullshit","smh",
}

# ======================================
# STYLE / TONE — SLANG EXPANDED
# ======================================

FLIRTY = {
    "cute","cutie","qt","hot","handsome","beautiful","pretty",
    "sexy","kiss","kisses","xoxo","mwah","😘","😍","😉","😏",
    "flirt","tease","teasing",
    "hey you","hey sexy","hey cutie","damn u cute","babe","baby","sweety"
}

SEXUAL = {
    "sex","fuck","fucking","horny","wet","hard","naked",
    "dick","cock","pussy","boobs","tits","ass","booty",
    "cum","cumming","breed","breedable",
    "thrust","ride","mount","spread","bed","moan","mm","mmm"
}

CURSE = {
    "fuck","fucking","shit","damn","bitch","asshole",
    "crap","hell","pissed","wtf","ffs","af","asf",
    "omfg","holy shit"
}

# =================================================
# LITE SUMMARY PHRASES
# =================================================

PRIMARY_PHRASE = {
    "engaging": "Easily draws others into conversation",
    "curious": "Shows interest in people nearby",
    "humorous": "Brings light humor into chat",
    "supportive": "Creates a comfortable social tone",
    "dominant": "Naturally takes conversational lead",
    "combative": "Expresses opinions strongly",
}

SECONDARY_PHRASE = {
    "engaging": "keeps interactions moving",
    "curious": "asks questions and observes",
    "humorous": "adds playful moments",
    "supportive": "smooths social flow",
    "dominant": "directs conversations",
    "combative": "pushes back when challenged",
}

LITE_MODIFIERS = [
    "in a relaxed way",
    "without overdoing it",
    "when the moment fits",
    "in casual situations",
    "as conversations unfold",
]

# =================================================
# ROOM VIBE (LITE)
# =================================================

ROOM_ACTIVITY = {
    "quiet": "Mostly quiet with minimal chatter",
    "low": "Light conversation happening",
    "medium": "Steady social interaction",
    "high": "Active and socially charged",
}

ROOM_DESCRIPTORS = [
    "Easygoing and approachable",
    "Calm with light engagement",
    "Casual social atmosphere",
    "Comfortable and low-pressure",
    "Warm but not overwhelming",
]

# =================================================
# NEARBY (LITE)
# =================================================

NEARBY_TAGS = [
    "quiet presence",
    "casual observer",
    "socially aware",
    "light conversational energy",
    "active participant",
]

# =================================================
# HELPERS
# =================================================

def decay(ts):
    age = (NOW - ts) / 3600
    if age <= 1: return 1.0
    if age <= 24: return 0.7
    return 0.4

def extract_hits(text):
    hits = defaultdict(int)
    if not text:
        return hits

    words = re.findall(r"\b\w+\b", text.lower())

    def neg(i):
        return any(w in NEGATORS for w in words[max(0,i-3):i])

    for i,w in enumerate(words):
        if neg(i): continue
        if w in ENGAGING: hits["engaging"] += 1
        if w in CURIOUS: hits["curious"] += 1
        if w in HUMOR: hits["humorous"] += 1
        if w in SUPPORT: hits["supportive"] += 1
        if w in DOMINANT: hits["dominant"] += 1
        if w in COMBATIVE: hits["combative"] += 1
        if w in FLIRTY: hits["flirty"] += 1
        if w in SEXUAL: hits["sexual"] += 1
        if w in CURSE: hits["curse"] += 1

    return hits

# =================================================
# DATA FETCH
# =================================================

def fetch_rows():
    r = requests.get(GOOGLE_PROFILES_FEED, timeout=20)
    m = re.search(r"setResponse\((\{.*\})\)", r.text, re.S)
    payload = json.loads(m.group(1))
    cols = [c["label"] for c in payload["table"]["cols"]]

    rows = []
    for row in payload["table"]["rows"]:
        rec = {}
        for i, cell in enumerate(row["c"]):
            rec[cols[i]] = cell["v"] if cell else 0
        rows.append(rec)
    return rows

# =================================================
# BUILD PROFILES (LITE)
# =================================================

def build_profiles():
    if CACHE["profiles"] and time.time() - CACHE["ts"] < CACHE_TTL:
        return CACHE["profiles"]

    rows = fetch_rows()
    profiles = {}

    for r in rows:
        uid = r.get("avatar_uuid")
        if not uid:
            continue

        ts = float(r.get("timestamp", NOW))
        w = decay(ts)

        p = profiles.setdefault(uid, {
            "avatar_uuid": uid,
            "name": r.get("display_name", "Unknown"),
            "messages": 0,
            "traits": defaultdict(float),
            "recent": 0
        })

        msgs = max(int(r.get("messages", 1)), 1)
        p["messages"] += msgs * w

        if NOW - ts < 3600:
            p["recent"] += msgs

        hits = extract_hits(r.get("context_sample", ""))
        for k,v in hits.items():
            if k in PRIMARY_PHRASE:
                p["traits"][k] += v * w

    out = []

    for p in profiles.values():
        m = max(p["messages"],1)
        conf = min(1.0, math.log(m+1)/4)

        traits = {k:(v/m) for k,v in p["traits"].items()}
        out.append({
            "avatar_uuid": p["avatar_uuid"],
            "name": p["name"],
            "confidence": int(conf*100),
            "recent": p["recent"],
            "traits": traits
        })

    CACHE["profiles"] = out
    CACHE["ts"] = time.time()
    return out

# =================================================
# LITE SUMMARY ENGINE
# =================================================

def build_lite_summary(p):
    if not p or not p["traits"]:
        return "Limited data. Social patterns still forming."

    ranked = sorted(p["traits"].items(), key=lambda x: x[1], reverse=True)
    top = [k for k,v in ranked if v > 0][:2]

    if not top:
        return "Present, but not enough activity yet."

    line = PRIMARY_PHRASE[top[0]]

    if len(top) > 1:
        line += ", " + SECONDARY_PHRASE[top[1]]

    line += " " + random.choice(LITE_MODIFIERS) + "."

    return line

# =================================================
# PRESENTATION (LITE)
# =================================================

def present_profile(p):
    return (
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📊 MY PROFILE (LITE)\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"{p['name']}\n\n"
        f"{build_lite_summary(p)}\n\n"
        "🔓 Full version unlocks deep traits.\n"
        "━━━━━━━━━━━━━━━━━━━━"
    )

def present_nearby(profiles):
    if not profiles:
        return "👥 Nearby: No one detected."

    lines = [
        "━━━━━━━━━━━━━━━━━━━━",
        "👥 NEARBY (LITE)",
        "━━━━━━━━━━━━━━━━━━━━"
    ]

    for p in profiles[:6]:
        lines.append(f"• {p['name']} — {random.choice(NEARBY_TAGS)}")

    lines.append("")
    lines.append("🔍 Click a name to preview.")
    lines.append("━━━━━━━━━━━━━━━━━━━━")

    return "\n".join(lines)

def build_room_vibe(profiles):
    recent = sum(1 for p in profiles if p["recent"] > 0)

    if recent == 0:
        level = "quiet"
    elif recent < 3:
        level = "low"
    elif recent < 6:
        level = "medium"
    else:
        level = "high"

    return (
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🌙 ROOM VIBE (LITE)\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"{ROOM_ACTIVITY[level]}.\n"
        f"{random.choice(ROOM_DESCRIPTORS)}.\n\n"
        "🔓 Full version shows live shifts.\n"
        "━━━━━━━━━━━━━━━━━━━━"
    )

# =================================================
# ENDPOINTS
# =================================================

@app.route("/profile/self", methods=["POST"])
def profile_self():
    data = request.get_json(silent=True) or {}
    uuid = data.get("uuid")

    profiles = build_profiles()
    me = next((p for p in profiles if p["avatar_uuid"] == uuid), None)

    return jsonify({"text": present_profile(me)})

@app.route("/profile/lookup", methods=["POST"])
def profile_lookup():
    data = request.get_json(silent=True) or {}
    name = data.get("name")

    return jsonify({
        "text": (
            f"📍 {name} (Lite)\n\n"
            "Social energy detected.\n"
            "General engagement present.\n\n"
            "🔓 Full version reveals compatibility."
        )
    })

@app.route("/room/vibe", methods=["POST"])
def room_vibe():
    profiles = build_profiles()
    return jsonify({"text": build_room_vibe(profiles)})

@app.route("/")
def ok():
    return "OK", 200
