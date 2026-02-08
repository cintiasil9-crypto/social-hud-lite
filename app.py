from flask import Flask, Response, jsonify, request
import os, time, math, requests, json, re
from collections import defaultdict

# =================================================
# APP SETUP
# =================================================

app = Flask(__name__)
GOOGLE_PROFILES_FEED = os.environ["GOOGLE_PROFILES_FEED"]

CACHE = {"profiles": None, "ts": 0}
CACHE_TTL = 300
NOW = time.time()

# =================================================
# KEYWORDS (SAME AS FULL)
# =================================================

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

# ======================================
# NEGATORS / REVERSALS — SL STYLE
# ======================================

NEGATORS = {
    "not","no","never","dont","don't","cant","can't",
    "isnt","isn't","wasnt","wasn't",
    "aint","ain't","nah","nope","naw",
    "idk","idc","dont care","doesnt matter"
}

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
            "styles": defaultdict(float),
            "recent": 0
        })

        msgs = max(int(r.get("messages", 1)), 1)
        p["messages"] += msgs * w

        if NOW - ts < 3600:
            p["recent"] += msgs

        hits = extract_hits(r.get("context_sample", ""))

        for k,v in hits.items():
            if k in ["engaging","curious","humorous","supportive","dominant","combative"]:
                p["traits"][k] += v * w
            if k in ["flirty","sexual","curse"]:
                p["styles"][k] += v * w

    out = []

    for p in profiles.values():
        m = max(p["messages"],1)
        conf = min(1.0, math.log(m+1)/4)

        out.append({
            "avatar_uuid": p["avatar_uuid"],
            "name": p["name"],
            "confidence": int(conf*100),
            "recent": p["recent"],
            "traits": {k:int((v/m)*100) for k,v in p["traits"].items()},
            "styles": {k:int((v/m)*100) for k,v in p["styles"].items()}
        })

    CACHE["profiles"] = out
    CACHE["ts"] = time.time()
    return out

# =================================================
# PRESENTATION (LITE)
# =================================================

def present_profile(p):
    if not p:
        return "👤 You:\nNo data yet."

    return (
        "━━━━━━━━━━━━━━━━━━━━\n"
        "👤 YOU (LITE)\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"Name: {p['name']}\n"
        f"Confidence: {p['confidence']}%\n\n"
        "Basic patterns detected.\n"
        "━━━━━━━━━━━━━━━━━━━━"
    )

def present_nearby(profiles):
    if not profiles:
        return "👥 Nearby:\nNo one detected."

    lines = ["━━━━━━━━━━━━━━━━━━━━","👥 NEARBY (LITE)","━━━━━━━━━━━━━━━━━━━━"]
    for p in profiles[:5]:
        lines.append(f"• {p['name']} ({p['confidence']}%)")
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)

def build_room_vibe(profiles):
    if not profiles:
        return "🧠 Room Vibe:\nQuiet"

    active = sum(1 for p in profiles if p["recent"] > 0)
    if active >= 5:
        vibe = "Active"
    elif active >= 2:
        vibe = "Warming up"
    else:
        vibe = "Calm"

    return (
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🧠 ROOM VIBE\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"Live energy: {vibe}\n"
        "━━━━━━━━━━━━━━━━━━━━"
    )

# =================================================
# ENDPOINTS
# =================================================

@app.route("/hud/scan", methods=["POST"])
def hud_scan():
    data = request.get_json(silent=True) or {}
    uuid = data.get("uuid")

    profiles = build_profiles()
    me = next((p for p in profiles if p["avatar_uuid"] == uuid), None)
    nearby = [p for p in profiles if p["avatar_uuid"] != uuid]

    room = build_room_vibe(nearby + ([me] if me else []))

    text = "\n\n".join([
        room,
        present_profile(me),
        present_nearby(nearby),
        "ℹ Detail improves as more residents participate."
    ])

    return Response(
        json.dumps({"text": text}, ensure_ascii=False),
        mimetype="application/json; charset=utf-8"
    )

@app.route("/profile/self", methods=["POST"])
def profile_self():
    data = request.get_json(silent=True) or {}
    uuid = data.get("uuid")

    if not uuid:
        return jsonify({"error": "missing uuid"}), 400

    # LITE summary
    text = (
        "📊 My Profile (Lite)\n"
        "• Social vibe: Balanced\n"
        "• Engagement: Medium\n"
        "• Data sample: Limited\n\n"
        "Upgrade to unlock full analytics."
    )

    return jsonify({"text": text})

@app.route("/profile/lookup", methods=["POST"])
def profile_lookup():
    data = request.get_json(silent=True) or {}
    name = data.get("name")

    if not name:
        return jsonify({"error": "missing name"}), 400

    text = (
        f"📊 {name} (Lite)\n"
        "• First impression: Neutral\n"
        "• Social energy: Moderate\n\n"
        "Upgrade to see deep traits."
    )

    return jsonify({"text": text})

@app.route("/room/vibe", methods=["POST"])
def room_vibe():
    text = (
        "🌈 Room Vibe (Lite)\n"
        "• Activity: Moderate\n"
        "• Energy: Mixed\n"
        "• Chat flow: Stable\n\n"
        "Full version shows live analytics."
    )

    return jsonify({"text": text})


@app.route("/")
def ok():
    return "OK", 200
